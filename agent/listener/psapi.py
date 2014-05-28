import psutil as ps
import os
import logging
import re
import platform
import psextensions

plugins = ''
root = None


class Node(object):

    def __init__(self, name, method=None, children=None, *args, **kwargs):
        if children is None:
            children = []
        if method is None:
            self.method = self.walk
        else:
            self.method = method
        self.children = children
        self.name = name
        self.lazy = False

    def accessor(self, path, *args, **kwargs):
        if path:
            for child in self.children:
                if child.name == path[0]:
                    return child.accessor(path=path[1:], *args, **kwargs)
            raise IndexError('No node with that name: %s' % path[0])
        else:
            kwargs['path'] = path[:1]
            return self.run(*args, **kwargs)

    def walk(self, *args, **kwargs):
        stat = {}
        for child in self.children:
            stat.update(child.run(walk=True, *args, **kwargs))
        return stat

    def run(self, walk=False, *args, **kwargs):
        if walk and self.lazy:
            return {self.name: 'lazy'}
        try:
            retval = self.method(*args, **kwargs)
        except TypeError:
            retval = self.method()
        return {self.name: retval}


class LazyNode(Node):

    def __init__(self, *args, **kwargs):
        super(LazyNode, self).__init__(*args, **kwargs)

    def accessor(self, path, *args, **kwargs):
        return self.run(path, *args, **kwargs)

    def run(self, path, *args, **kwargs):
        if path:
            return self.parse_query(path, *args, **kwargs)
        else:
            return {self.name: []}

    def parse_query(self, *args, **kwargs):
        raise Exception('Base class LazyNode was called, it is abstract, and you need to override this.')


class ProcessNode(LazyNode):

    def __init__(self, *args, **kwargs):
        super(ProcessNode, self).__init__(*args, **kwargs)

    def parse_query(self, path, *args, **kwargs):
        desired_proc = path[0].replace('|', '/')
        metrics = {'count': 0}
        for proc in ps.process_iter():
            if proc.name == desired_proc:
                metrics['count'] += 1
        try:
            if path[1] == 'count':
                return {'count': metrics['count']}
        except IndexError:
            return {desired_proc: metrics}


class ServiceNode(LazyNode):

    def __init__(self, *args, **kwargs):
        super(ServiceNode, self).__init__(*args, **kwargs)

    def run(self, path, *args, **kwargs):
        if path:
            return self.parse_query(path)
        else:
            try:
                return {self.name: psextensions.get_services()}
            except Exception, e:
                return {self.name: 'Error getting services: %s' % unicode(e)}

    def parse_query(self, path, *args, **kwargs):
        desired_service = path[0].replace('|', '/')

        try:
            desired_state = path[1]
        except IndexError:
            desired_state = None

        services = psextensions.get_services()

        if desired_state:
            return {desired_service: services.get(desired_service, 'Service not found') == desired_state}
        else:
            return {desired_service: services.get(desired_service, 'Service not found')}


def make_disk_nodes(disk_name):
    read_time = Node('read_time', method=lambda: (ps.disk_io_counters(perdisk=True)[disk_name].read_time, 'ms'))
    write_time = Node('write_time', method=lambda: (ps.disk_io_counters(perdisk=True)[disk_name].write_time, 'ms'))
    read_count = Node('read_count', method=lambda: (ps.disk_io_counters(perdisk=True)[disk_name].read_count, 'c'))
    write_count = Node('write_count', method=lambda: (ps.disk_io_counters(perdisk=True)[disk_name].write_count, 'c'))
    read_bytes = Node('read_bytes', method=lambda: (ps.disk_io_counters(perdisk=True)[disk_name].read_bytes, 'b'))
    write_bytes = Node('write_bytes', method=lambda: (ps.disk_io_counters(perdisk=True)[disk_name].write_bytes, 'b'))
    return Node(disk_name, children=[read_time, write_time, read_count, write_count, read_bytes, write_bytes])


def make_mountpoint_nodes(partition_name):
    mountpoint = partition_name.mountpoint
    total_size = Node('total_size', method=lambda: (ps.disk_usage(mountpoint).total, 'b'))
    used = Node('used', method=lambda: (ps.disk_usage(mountpoint).used, 'b'))
    free = Node('free', method=lambda: (ps.disk_usage(mountpoint).free, 'b'))
    used_percent = Node('used_percent', method=lambda: (ps.disk_usage(mountpoint).percent, '%'))
    device_name = Node('device_name', method=lambda: partition_name.device)
    safe_mountpoint = re.sub(r'[\\/]+', '|', mountpoint)
    return Node(safe_mountpoint, children=[total_size, used, free, used_percent, device_name])


def make_if_nodes(if_name):
    bytes_sent = Node('bytes_sent', method=lambda: (ps.net_io_counters(pernic=True)[if_name].bytes_sent, 'b'))
    bytes_recv = Node('bytes_recv', method=lambda: (ps.net_io_counters(pernic=True)[if_name].bytes_recv, 'b'))
    packets_sent = Node('packets_sent', method=lambda: (ps.net_io_counters(pernic=True)[if_name].packets_sent, 'c'))
    packets_recv = Node('packets_recv', method=lambda: (ps.net_io_counters(pernic=True)[if_name].packets_recv, 'c'))
    errin = Node('errin', method=lambda: (ps.net_io_counters(pernic=True)[if_name].errin, 'c'))
    errout = Node('errout', method=lambda: (ps.net_io_counters(pernic=True)[if_name].errout, 'c'))
    dropin = Node('dropin', method=lambda: (ps.net_io_counters(pernic=True)[if_name].dropin, 'c'))
    dropout = Node('dropout', method=lambda: (ps.net_io_counters(pernic=True)[if_name].dropout, 'c'))
    return Node(if_name, children=[bytes_sent, bytes_recv, packets_sent, packets_recv, errin, errout, dropin, dropout])


def get_system_node():
    sys_system = Node('system', method=lambda: platform.uname()[0])
    sys_node = Node('node', method=lambda: platform.uname()[1])
    sys_release = Node('release', method=lambda: platform.uname()[2])
    sys_version = Node('version', method=lambda: platform.uname()[3])
    sys_machine = Node('machine', method=lambda: platform.uname()[4])
    sys_processor = Node('processor', method=lambda: platform.uname()[5])
    return Node('system', children=[sys_system, sys_node, sys_release, sys_version, sys_machine, sys_processor])


def get_cpu_node():
    cpu_count = Node('count', method=lambda: len(ps.cpu_percent(percpu=True)))
    cpu_percent = Node('percent', method=lambda: (ps.cpu_percent(interval=1, percpu=True), '%'))
    cpu_user = Node('user', method=lambda: ([x.user for x in ps.cpu_times(percpu=True)], 'ms'))
    cpu_system = Node('system', method=lambda: ([x.system for x in ps.cpu_times(percpu=True)], 'ms'))
    cpu_idle = Node('idle', method=lambda: ([x.idle for x in ps.cpu_times(percpu=True)], 'ms'))
    cpu_percent.lazy = True
    return Node('cpu', children=[cpu_count, cpu_system, cpu_percent, cpu_user, cpu_idle])


def get_memory_node():
    mem_virt_total = Node('total', method=lambda: (ps.virtual_memory().total, 'b'))
    mem_virt_available = Node('available', method=lambda: (ps.virtual_memory().available, 'b'))
    mem_virt_percent = Node('percent', method=lambda: (ps.virtual_memory().percent, '%'))
    mem_virt_used = Node('used', method=lambda: (ps.virtual_memory().used, 'b'))
    mem_virt_free = Node('free', method=lambda: (ps.virtual_memory().free, 'b'))
    mem_virt = Node('virtual', children=(mem_virt_total, mem_virt_available, mem_virt_free, mem_virt_percent, mem_virt_used))
    mem_swap_total = Node('total', method=lambda: (ps.swap_memory().total, 'b'))
    mem_swap_percent = Node('percent', method=lambda: (ps.swap_memory().percent, '%'))
    mem_swap_used = Node('used', method=lambda: (ps.swap_memory().used, 'b'))
    mem_swap_free = Node('free', method=lambda: (ps.swap_memory().free, 'b'))
    mem_swap = Node('swap', children=[mem_swap_total, mem_swap_free, mem_swap_percent, mem_swap_used])
    return Node('memory', children=[mem_virt, mem_swap])


def get_disk_node():
    disk_counters = [make_disk_nodes(x) for x in list(ps.disk_io_counters(perdisk=True).keys())]

    disk_mountpoints = []
    for x in ps.disk_partitions():
        if os.path.isdir(x.mountpoint):
            tmp = make_mountpoint_nodes(x)
            disk_mountpoints.append(tmp)

    disk_logical = Node('logical', children=disk_mountpoints)
    disk_physical = Node('physical', children=disk_counters)

    return Node('disk', children=[disk_physical, disk_logical])


def get_interface_node():
    if_children = [make_if_nodes(x) for x in list(ps.net_io_counters(pernic=True).keys())]
    return Node('interface', children=if_children)


def get_agent_node():

    def walk_plugins():
        global plugins
        lat = []
        for plugin in os.listdir(plugins):
            plugin_path = os.path.join(plugins, plugin)
            logging.info(plugin_path)
            if os.path.isfile(plugin_path):
                lat.append(plugin)
        return lat

    plugin = Node('plugin', method=walk_plugins)
    return Node('agent', children=(plugin,))


def get_user_node():
    user_count = Node('count', method=lambda: (len([x.name for x in ps.get_users()]), 'c'))
    user_list = Node('list', method=lambda: [x.name for x in ps.get_users()])
    return Node('user', children=[user_count, user_list])


def get_process_node():
    return ProcessNode('process')


def get_service_node():
    return ServiceNode('service')


def get_root_node():
    cpu = get_cpu_node()
    memory = get_memory_node()
    disk = get_disk_node()
    interface = get_interface_node()
    agent = get_agent_node()
    user = get_user_node()
    process = get_process_node()
    service = get_service_node()
    system = get_system_node()
    return Node('root', children=[cpu, memory, disk, interface, agent, user, process, service, system])


def init_root(*args):
    global root
    root = get_root_node()
    for n in args:
        root.children.append(n)


def getter(accessor='', s_plugins='', *args, **kwargs):
    global plugins
    logging.debug('Getting accessor: %s', accessor)
    logging.debug("Using %s" % s_plugins)
    plugins = os.path.abspath(os.path.normpath(s_plugins))
    path = [x for x in accessor.split('/') if x]
    if len(path) > 0 and path[0] == 'api':
        path = path[1:]
    return root.accessor(path, *args, **kwargs)
