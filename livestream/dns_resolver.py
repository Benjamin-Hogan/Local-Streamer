from dnslib.server import DNSServer, BaseResolver
from dnslib import RR, QTYPE, A


def get_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP


class HoganDNSResolver(BaseResolver):
    def resolve(self, request, handler):
        reply = request.reply()
        qname = str(request.q.qname)

        if "hoganlivestream." in qname:
            ip = get_ip()
            reply.add_answer(RR(qname, QTYPE.A, rdata=A(ip), ttl=300))
        return reply


def start_dns_server():
    resolver = HoganDNSResolver()
    dns_server = DNSServer(resolver, port=53, address="0.0.0.0", tcp=False)
    dns_server.start_thread()
    print("DNS server started on port 53")
