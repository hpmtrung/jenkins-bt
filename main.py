import json
import logging as log
import threading
import time
from enum import Enum
from logging.handlers import RotatingFileHandler
from pathlib import Path

import click
import yaml
from jenkins import Jenkins
from rich.live import Live
from rich.table import Table

RETRIES_COUNT_GET_BUILD_STAGE = 20
RETRIES_INTERVAL_SECONDS_GET_BUILD_STAGE = 2
INTERVAL_SECONDS_REFRESH_BUILD = 2

log_directory = Path.home() / 'jenkins-bt-logs'
log_directory.mkdir(parents=True, exist_ok=True)

# Configure logging
log.basicConfig(
    level=log.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        RotatingFileHandler(
            log_directory / "build.log", maxBytes=1000000, backupCount=2  # 1MB max, keep 2 backups
        )
    ]
)


class BuildStatus(Enum):
    IN_PROGRESS = 1
    SUCCESS = 2
    FAILED = 3


class Node:
    def __init__(self, name: str):
        self.name = name
        self.inbound = 0
        self.children: list[Node] = []

    def __eq__(self, other):
        return self.name == other.name

    def __hash__(self):
        return hash(self.name)

    def __repr__(self):
        return f"name={self.name}, inbound={self.inbound}, children={[n.name for n in self.children]}"


class BuildItem:
    def __init__(self):
        self.job_name = ""
        self.build_num = 0
        self.status = ""
        self.stage = ""
        self.duration = 0

    def __repr__(self):
        return f"job_name={self.job_name}, build_num={self.build_num}, status={self.status}, stage={self.stage}, duration={self.duration}s"


class Authentication:
    def __init__(self):
        self.username = ""
        self.api_token = ""


class Config:
    auth = Authentication()
    endpoint = ""
    aliases: dict[str, str] = {}
    dependencies: list[list[int]] = []


def build_graph(aliases: dict[str, str], dependencies: list[list[int]]) -> dict[str, str]:
    name_node_mapping = {}
    for alias in aliases.keys():
        name_node_mapping.setdefault(alias, Node(alias))

    for dep in dependencies:
        src_node = name_node_mapping.get(dep[0])
        dst_node = name_node_mapping.get(dep[1])

        dst_node.children.append(src_node)
        src_node.inbound += 1
    return name_node_mapping


def get_topo_sort(start_node: str) -> list[list[Node]]:
    layers = []

    current_queue = [start_node]
    next_queue = []

    while len(current_queue) != 0:
        layers.append(current_queue[:])
        next_queue = []
        for node in current_queue:
            for child in node.children:
                child.inbound -= 1
                if child.inbound == 0:
                    next_queue.append(child)
        current_queue = next_queue

    return layers


def init_jenkins(endpoint: str, auth: Authentication):
    return Jenkins(endpoint, auth.username, auth.api_token)


def get_next_build_num(jenkins: Jenkins, job_name: str):
    return jenkins.get_job_info(job_name)['nextBuildNumber']


def write_json(file_name: str, data):
    with open(file_name, 'w', encoding='utf-8') as f:
        f.write(json.dumps(data, indent=2))


def build_job(jenkins: Jenkins, job_name: str):
    jenkins.build_job(job_name)


def generate_table(build_items: list[BuildItem]) -> Table:
    table = Table(box=None, show_edge=False)
    table.add_column("Job", justify="left", no_wrap=True, width=25)
    table.add_column("Build", justify="left", no_wrap=True, width=8)
    table.add_column("Status", justify="left", no_wrap=True, width=15)
    table.add_column("Stage", justify="left", no_wrap=True, width=25)
    table.add_column("Duration (s)", justify="right", no_wrap=True, width=15)

    for item in build_items:
        table.add_row(item.job_name, f"#{item.build_num}", item.status, item.stage, str(item.duration))

    return table


def resolve_statuses(statuses: list[str], ignore_failed: bool) -> BuildStatus:
    if statuses and statuses.count("SUCCESS") == len(statuses):
        return BuildStatus.SUCCESS
    if not ignore_failed and statuses.count('ABORTED') > 0 or statuses.count('FAILED') > 0:
        return BuildStatus.FAILED
    return BuildStatus.IN_PROGRESS


def process_aliases(data: list[dict[str, str]]) -> dict[str, str]:
    aliases = {}
    if data != None:
        for pair in data:
            for alias, job_name in pair.items():
                aliases[alias] = job_name
    return aliases


def process_dependencies(data: list[dict[str, str]]) -> list[list[int]]:
    dependencies = []
    if data != None:
        for pair in data:
            for src_alias, dst_alias in pair.items():
                dependencies.append((src_alias, dst_alias))
    return dependencies


def read_conf_file(file_name: str) -> Config:
    data = {}
    with open(file_name, "r", encoding="utf-8") as f:
        data = yaml.load(f, yaml.CLoader)

    endpoint = data['endpoint']
    auth = data['auth']
    if endpoint == None:
        raise AssertionError('Endpoint required')
    if auth == None:
        raise AssertionError('Authentication required')

    config = Config()
    config.endpoint = endpoint
    config.auth.username = auth['username']
    config.auth.api_token = auth['api-token']
    config.aliases = process_aliases(data['aliases'])
    config.dependencies = process_dependencies(data['dependencies'])
    return config


def init_build_items(nodes: list[Node], aliases: dict[str, str], jenkins: Jenkins) -> list[BuildItem]:
    build_items = []
    for node in nodes:
        build_item = BuildItem()
        build_item.job_name = aliases[node.name]
        build_item.build_num = get_next_build_num(jenkins, build_item.job_name)
        build_item.status = 'INITIATED'
        build_item.stage = '?'

        build_items.append(build_item)
    return build_items


def submit_build_and_wait(build_items: list[BuildItem], jenkins: Jenkins):
    threads = []
    for item in build_items:
        thread = threading.Thread(target=build_job, args=(jenkins, item.job_name))
        thread.start()
        threads.append(thread)
    for t in threads:
        t.join()


def update_build_item_from_stage_info(item: BuildItem, stage_info: dict[str, str]):
    item.status = stage_info['status']
    item.duration = stage_info['durationMillis'] / 1000

    stages = stage_info['stages']
    if stages != None and len(stages) > 0:
        item.stage = stages[-1]['name']


def get_build_stage_info(item: BuildItem, jenkins: Jenkins) -> dict[str, str]:
    stage_info = {}
    try_count = 0
    while not stage_info and try_count < RETRIES_COUNT_GET_BUILD_STAGE:
        stage_info = jenkins.get_build_stages(item.job_name, item.build_num)
        try_count += 1
        time.sleep(RETRIES_INTERVAL_SECONDS_GET_BUILD_STAGE)

    if not stage_info:
        raise IOError(f"Failed to get build stage info for job {item.job_name}")
    return stage_info


def filter_excluded_nodes(build_phases: list[list[Node]], exclude_aliases: set[str]) -> list[list[Node]]:
    result = []
    for nodes in build_phases:
        nodes_copy = set(nodes)
        for node in nodes:
            if node.name in exclude_aliases:
                nodes_copy.remove(node)
        if nodes_copy:
            result.append(nodes_copy)
    return result


def build_phase(nodes: list[Node], aliases: dict[str, str], jenkins: Jenkins, ignore_failed: bool) -> BuildStatus:
    build_items = init_build_items(nodes, aliases, jenkins)
    submit_build_and_wait(build_items, jenkins)

    phase_status = BuildStatus.IN_PROGRESS
    with Live(generate_table(build_items)) as live:
        while True:
            time.sleep(INTERVAL_SECONDS_REFRESH_BUILD)

            statuses = []
            for item in build_items:
                if item.status not in ['FAILED', 'ABORTED', 'SUCCESS']:
                    try:
                        stage_info = get_build_stage_info(item, jenkins)
                        update_build_item_from_stage_info(item, stage_info)
                    except Exception:
                        log.error("Failed to update build status", exc_info=True)
                        item.status = 'FAILED'
                statuses.append(item.status)

            live.update(generate_table(build_items))

            phase_status = resolve_statuses(statuses, ignore_failed)
            if phase_status in [BuildStatus.FAILED, BuildStatus.SUCCESS]:
                break

    if not ignore_failed and phase_status == BuildStatus.FAILED:
        return BuildStatus.FAILED

    return BuildStatus.IN_PROGRESS


@click.command()
@click.option('-f', '--config-file', default=Path.home() / 'jenkins-bt-config.yml', help='Path to yaml config file')
@click.option('-s', '--start-point', help='An alias of starting point')
@click.option('-e', '--exclude-aliases', multiple=True, help='List of aliases to be excluded')
@click.option('--ignore-failed', is_flag=True, default=False,
              help='Ignore failed jobs on build progress. Default: false (ie. fail-fast)')
def main(config_file: str, start_point: str, exclude_aliases: set[str], ignore_failed: bool):
    log.info(
        f'config_file={config_file}, start_point={start_point}, exclude_aliases={exclude_aliases}, ignore_failed={ignore_failed}')

    if not start_point:
        print('Start point is required!')
        exit(0)

    config = read_conf_file(config_file)

    jenkins = init_jenkins(config.endpoint, config.auth)
    graph = build_graph(config.aliases, config.dependencies)

    build_phases = get_topo_sort(graph.get(start_point))

    if exclude_aliases:
        build_phases = filter_excluded_nodes(build_phases, exclude_aliases)

    if not build_phases:
        print('No job built!')
        return

    total_jobs = sum([len(p) for p in build_phases])
    print(f'Total jobs: {total_jobs}. Total phases: {len(build_phases)}\n')

    final_status = BuildStatus.SUCCESS

    for phase in range(len(build_phases)):
        print(f"Build phase #{phase + 1}:")
        phase_status = build_phase(build_phases[phase], config.aliases, jenkins, ignore_failed)
        if phase_status == BuildStatus.FAILED:
            final_status = BuildStatus.FAILED
            break
    print(f"\nFinal build status: {final_status.name}")


if __name__ == "__main__":
    main()