import logging
import random
import time
import uuid
from collections import defaultdict
from typing import Dict

from galileoexperiments.api.model import Pod
from galileoexperiments.utils.constants import function_label, zone_label
from galileoexperiments.utils.helpers import set_weights_rr, EtcdClient
from galileoexperiments.utils.k8s import spawn_pods, get_pods, remove_pods
from galileoexperimentsextensions.mobilenet.app import MobilenetProfilingApplication
from kubernetes import client, config

logger = logging.getLogger(__name__)

max_pods = 10
max_pods_per_node = 4
min_pods = 1

etcd_client = EtcdClient.from_env()
fn_label = 'mobilenet'
image = 'edgerun/mobilenet-inference:1.0.0'
pod_prefix = 'deployment'
pod_factory = MobilenetProfilingApplication().pod_factory
etcd_service_key = None
# store pods by zone, and node
pod_map = defaultdict(lambda: defaultdict(list))
pod_id_idx = 0
keys = set()

random.seed(42)


def get_load_balancer_pods() -> Dict[str, Pod]:
    pods = fetch_pods('type', 'api-gateway')
    lb = {}
    for pod in pods:
        # pod name, i.e.: go-load-balancer-deployment-zone-b-xwg9c
        pod_name = pod.metadata.name
        zone = f"zone-{pod_name.split('-')[5]}"
        ip = pod.status.pod_ip
        # not used
        pod_id = ''
        labels = {
            'type': 'api-gateway',
            zone_label: zone
        }
        lb[zone] = Pod(pod_id, ip, labels, pod_name)
    return lb


def spawn(cluster, lbs, node, labels):
    postfix = str(uuid.uuid4())[:5]
    # create new instance
    pod_name = spawn_pods(image, f'{fn_label}-{pod_prefix}-{postfix}', node, labels, 1, pod_factory)[0]
    # update internal state to include newly created pod
    pod_map[cluster][node].append(pod_name)

    # blocks until pod is available
    get_pods([pod_name])

    # update weights
    update_weights(lbs)


def teardown(name):
    remove_pods([name])


def fetch_pod_names(label: str, value: str):
    config.load_kube_config()
    v1 = client.CoreV1Api()
    pods_list = v1.list_namespaced_pod('default')
    pods = []
    for pod in pods_list.items:
        fn_value = pod.metadata.labels.get(label)
        if fn_value == value:
            pods.append(pod.metadata.name)
    return pods


def fetch_pods(label: str, value: str):
    config.load_kube_config()
    v1 = client.CoreV1Api()
    pods_list = v1.list_namespaced_pod('default')
    pods = []
    for pod in pods_list.items:
        if pod.metadata.labels is None:
            continue

        fn_value = pod.metadata.labels.get(label)
        if fn_value == value:
            pods.append(pod)
    return pods


def do_chaos(nodes, lbs):
    logger.info("Chooses action...")
    a = random.random()

    if a < 0.1:
        logger.info("Do nothing")
    elif 0.1 <= a < 0.5:
        node = random.choice(nodes)
        cluster = node[1]
        node_name = node[0]
        labels = {
            function_label: fn_label,
            zone_label: cluster
        }

        logger.info(f"Try to scale up on node {node_name}")

        too_much_pods = True
        if len(pod_map[cluster][node_name]) < max_pods_per_node:
            no_pods = count_all_pods()
            if no_pods + 1 <= max_pods:
                too_much_pods = False

        if too_much_pods:
            logger.info(f"Scale up on node {node_name} aborted, too many pods already running")
        else:
            spawn(cluster, lbs, node_name, labels)
    else:
        # first check if enough pods are in the cluster
        no_pods = count_all_pods()
        if no_pods - 1 < min_pods:
            logger.info(f"Not enough pods ({no_pods}) running to scale down. Minimum: {min_pods}")
            return

        # now we fetch all nodes that have at least one pod instance running
        scale_down_candidates = []
        for node in nodes:
            node_name = node[0]
            cluster = node[1]
            if len(pod_map[cluster][node_name]) > 0:
                scale_down_candidates.append(node)

        # select one random node to scale down
        node = random.choice(scale_down_candidates)
        node_name = node[0]
        cluster = node[1]
        logger.info(f"Scale down on node {node_name}")
        scale_down(cluster, lbs, node_name)


def count_all_pods() -> int:
    count = 0
    for node_dict in pod_map.values():
        for pods in node_dict.values():
            count += len(pods)
    return count


def scale_down(cluster, lbs, node):
    # choose a random pod on the node
    to_remove = random.choice(pod_map[cluster][node])

    # remove pod from internal state
    pod_map[cluster][node].remove(to_remove)

    # update load balancer weight of cluster to not include the removed pod anymore
    update_weights(lbs)

    # teardown the pod
    teardown(to_remove)


def update_weights(lbs):
    for cluster in lbs.keys():
        # fetch pods in cluster
        pods = get_pods(pods_in_cluster(cluster))

        # look for other clusters that node the function
        for lb_cluster, lb_pod in lbs.items():
            if lb_cluster == cluster:
                continue
            else:
                if cluster_hosts_function(lb_cluster):
                    pods.append(lb_pod)

        # update weights
        keys.add(set_weights_rr(pods, cluster, fn_label))


def pods_in_cluster(cluster):
    pods = []
    for node, node_pods in pod_map[cluster].items():
        pods.extend(node_pods)
    return pods


def cluster_hosts_function(cluster):
    node_function = False
    for node, pods in pod_map[cluster].items():
        if len(pods) > 0:
            node_function = True
            break
    return node_function


def cleanup():
    for node_dict in pod_map.values():
        for pod_list in node_dict.values():
            for pod in pod_list:
                try:
                    teardown(pod)
                except Exception:
                    pass
    for key in keys:
        etcd_client.remove(key)


def main():
    logging.basicConfig(level=logging._nameToLevel['INFO'])

    initial_pod_count = 2
    should_cleanup = True
    duration = 50
    reconcile_interval = 5

    logger.info('Start random scaler, that scales up the application at random')
    nodes = [
        ('eb-a-controller', 'zone-a'),
        ('eb-a-jetson-nx-0', 'zone-a'),
        ('eb-b-controller', 'zone-b'),
        ('eb-b-xeon-0', 'zone-b'),
        ('eb-b-xeon-1', 'zone-b'),
        ('eb-c-vm-0', 'zone-c')
    ]

    lbs = get_load_balancer_pods()

    fn_pods = fetch_pods(function_label, fn_label)
    while len(fn_pods) != initial_pod_count:
        logger.info(f'no function pods "{fn_label}" found. sleep 3 seconds...')
        time.sleep(5)
        fn_pods = fetch_pods(function_label, fn_label)

    for pod in fn_pods:
        node = pod.spec.node_name
        pod_map[pod.metadata.labels[zone_label]][node].append(pod.metadata.name)
        pass

    start = time.time()

    try:
        now = start
        while now <= start + duration:
            do_chaos(nodes, lbs)
            time.sleep(reconcile_interval)
            now = time.time()
    finally:
        if should_cleanup:
            cleanup()


if __name__ == '__main__':
    main()
