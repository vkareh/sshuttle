import socket
from sshuttle.firewall import subnet_weight
from sshuttle.helpers import family_to_string, which, debug2
from sshuttle.linux import ipt, ipt_ttl, ipt_chain_exists, nonfatal
from sshuttle.methods import BaseMethod


class Method(BaseMethod):

    # We name the chain based on the transproxy port number so that it's
    # possible to run multiple copies of sshuttle at the same time.  Of course,
    # the multiple copies shouldn't have overlapping subnets, or only the most-
    # recently-started one will win (because we use "-I OUTPUT 1" instead of
    # "-A OUTPUT").
    def setup_firewall(self, port, dnsport, nslist, family, subnets, udp,
                       user, ttl):
        # only ipv4 supported with NAT
        if family != socket.AF_INET:
            raise Exception(
                'Address family "%s" unsupported by nat method_name'
                % family_to_string(family))
        if udp:
            raise Exception("UDP not supported by nat method_name")

        table = "nat"

        def _ipt(*args):
            return ipt(family, table, *args)

        def _ipt_ttl(*args):
            return ipt_ttl(family, table, *args)

        def _ipm(*args):
            return ipt(family, "mangle", *args)

        chain = 'sshuttle-%s' % port

        # basic cleanup/setup of chains
        self.restore_firewall(port, family, udp, user)

        _ipt('-N', chain)
        _ipt('-F', chain)
        if user is not None:
            _ipm('-I', 'OUTPUT', '1', '-m', 'owner', '--uid-owner', str(user),
                 '-j', 'MARK', '--set-mark', str(port))
            args = '-m', 'mark', '--mark', str(port), '-j', chain
        else:
            args = '-j', chain

        _ipt('-I', 'OUTPUT', '1', *args)
        _ipt('-I', 'PREROUTING', '1', *args)

        # This TTL hack allows the client and server to run on the
        # same host. The connections the sshuttle server makes will
        # have TTL set to 63.
        _ipt_ttl('-A', chain, '-j', 'RETURN', '-m', 'ttl', '--ttl', '%s' % ttl)

        # Redirect DNS traffic as requested. This includes routing traffic
        # to localhost DNS servers through sshuttle.
        for _, ip in [i for i in nslist if i[0] == family]:
            _ipt('-A', chain, '-j', 'REDIRECT',
                 '--dest', '%s/32' % ip,
                 '-p', 'udp',
                 '--dport', '53',
                 '--to-ports', str(dnsport))

        # Don't route any remaining local traffic through sshuttle.
        _ipt('-A', chain, '-j', 'RETURN',
             '-m', 'addrtype',
             '--dst-type', 'LOCAL')

        # create new subnet entries.
        for _, swidth, sexclude, snet, fport, lport \
                in sorted(subnets, key=subnet_weight, reverse=True):
            tcp_ports = ('-p', 'tcp')
            if fport:
                tcp_ports = tcp_ports + ('--dport', '%d:%d' % (fport, lport))

            if sexclude:
                _ipt('-A', chain, '-j', 'RETURN',
                     '--dest', '%s/%s' % (snet, swidth),
                     *tcp_ports)
            else:
                _ipt('-A', chain, '-j', 'REDIRECT',
                     '--dest', '%s/%s' % (snet, swidth),
                     *(tcp_ports + ('--to-ports', str(port))))

    def restore_firewall(self, port, family, udp, user):
        # only ipv4 supported with NAT
        if family != socket.AF_INET:
            raise Exception(
                'Address family "%s" unsupported by nat method_name'
                % family_to_string(family))
        if udp:
            raise Exception("UDP not supported by nat method_name")

        table = "nat"

        def _ipt(*args):
            return ipt(family, table, *args)

        def _ipt_ttl(*args):
            return ipt_ttl(family, table, *args)

        def _ipm(*args):
            return ipt(family, "mangle", *args)

        chain = 'sshuttle-%s' % port

        # basic cleanup/setup of chains
        if ipt_chain_exists(family, table, chain):
            if user is not None:
                nonfatal(_ipm, '-D', 'OUTPUT', '-m', 'owner', '--uid-owner',
                         str(user), '-j', 'MARK', '--set-mark', str(port))
                args = '-m', 'mark', '--mark', str(port), '-j', chain
            else:
                args = '-j', chain
            nonfatal(_ipt, '-D', 'OUTPUT', *args)
            nonfatal(_ipt, '-D', 'PREROUTING', *args)
            nonfatal(_ipt, '-F', chain)
            _ipt('-X', chain)

    def get_supported_features(self):
        result = super(Method, self).get_supported_features()
        result.user = True
        return result

    def is_supported(self):
        if which("iptables"):
            return True
        debug2("nat method not supported because 'iptables' command "
               "is missing.")
        return False
