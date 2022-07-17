import logging
import sys

from galileo.shell.shell import init
from galileo.worker.context import Context
from galileoexperiments.api.model import ScenarioWorkloadConfiguration
from galileoexperiments.experiment.scenario.run import run_scenario_workload

from galileoexperimentsextensions.mobilenet.app import MobilenetProfilingApplication

logger = logging.getLogger(__name__)


def main():
    logging.basicConfig(level=logging._nameToLevel['INFO'])
    creator = 'edgerun'
    mobilenet_image = 'edgerun/mobilenet-inference:1.0.0'
    app_names = {
        mobilenet_image: 'mobilenet'
    }

    master_node = 'eb-k3s-master'

    # node to service mapping including the number of service instances
    services = {
        'eb-c-vm-0': {
            mobilenet_image: 2
        }
    }

    # maps nodes that should host applications to zones
    cluster_a = 'zone-a'
    cluster_b = 'zone-b'
    cluster_c = 'zone-c'
    zone_mapping = {
        'eb-c-vm-0': cluster_c,
    }

    params = {}

    # parameters for each image (used to initialize the clients)
    app_params = {
        mobilenet_image: {
            'service': {
                'name': 'mobilenet',
                # 'location': 'https://i.imgur.com/0jx0gP8.png',
                # 'remote': True,
                'location': 'data/pictures/dog.jpg',
                'remote': False
            }
        }
    }

    profiling_apps = {
        mobilenet_image: MobilenetProfilingApplication()
    }

    # Instantiate galileo context that includes all dependencies needed to execute an experiment
    ctx = Context()
    rds = ctx.create_redis()
    g = init(rds)

    # contains 4 requests
    scenario_profile = 'data/profiles/scenario_profile.pkl'

    # client profiles, each starts one client that sends to the zone's load balancer
    profiles = {
        cluster_a: {
            mobilenet_image: [scenario_profile, scenario_profile],
        },
        cluster_b: {
            mobilenet_image: [scenario_profile]
        }
    }

    config = ScenarioWorkloadConfiguration(
        creator=creator,
        app_names=app_names,
        master_node=master_node,
        services=services,
        zone_mapping=zone_mapping,
        params=params,
        app_params=app_params,
        profiling_apps=profiling_apps,
        context=g,
        profiles=profiles
    )

    run_scenario_workload(config)


if __name__ == '__main__':
    main()
