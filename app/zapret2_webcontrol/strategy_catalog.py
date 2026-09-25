from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReferenceStrategySpec:
    """Exact strategy data observed in the reference LuCI installation."""

    name: str
    enabled: bool
    protocol: str
    ports: tuple[str, ...]
    filter_l7: tuple[str, ...]
    hostlist: str | None
    script: str


def _spec(
    name: str,
    *,
    enabled: bool = False,
    protocol: str = "tcp",
    ports: tuple[str, ...] = ("443",),
    filter_l7: tuple[str, ...] = ("tls",),
    hostlist: str | None = None,
    script: str,
) -> ReferenceStrategySpec:
    return ReferenceStrategySpec(
        name=name,
        enabled=enabled,
        protocol=protocol,
        ports=ports,
        filter_l7=filter_l7,
        hostlist=hostlist,
        script=script.strip(),
    )


_BASE_V = (
    _spec("v1", script="""
--payload=tls_client_hello
--lua-desync=multisplit:pos=2:seqovl=681:seqovl_pattern=blob_stun
"""),
    _spec("v2", script="""
--payload=tls_client_hello
--lua-desync=fake:blob=blob_tls_clienthello_www_google_com:optional:tcp_ts=-600000:repeats=8:tls_mod=rnd,dupsid,sni=www.google.com
--lua-desync=multisplit:pos=1:seqovl=681:seqovl_pattern=blob_stun
"""),
    _spec("v3", script="""
--payload=tls_client_hello
--lua-desync=hostfakesplit:host=ozon.ru:tcp_ts=-600000:tcp_md5:repeats=4
"""),
    _spec("v4", script="""
--payload=tls_client_hello
--lua-desync=multisplit:pos=1:seqovl=582:seqovl_pattern=blob_stun
"""),
    _spec("v5", script="""
--payload=tls_client_hello
--lua-desync=fake:blob=blob_stun:tcp_seq=0:tcp_ack=-66000:badsum
--lua-desync=fakeddisorder:pos=1:pattern=blob_tls_clienthello_www_google_com:tcp_seq=0:tcp_ack=-66000:badsum
"""),
    _spec("v6", script="""
--payload=tls_client_hello
--lua-desync=hostfakesplit:midhost=host-2:host=i2.photo.2gis.com:tcp_seq=0:tcp_ack=-66000:badsum
"""),
    _spec("v7", script="""
--payload=tls_client_hello
--lua-desync=fake:blob=blob_stun:tcp_seq=-10000:tcp_ack=-66000:badsum:repeats=8
--lua-desync=multisplit:pos=1:seqovl=654:seqovl_pattern=blob_stun
"""),
    _spec("v8", script="""
--payload=tls_client_hello
--lua-desync=fake:blob=blob_tls_clienthello_www_4pda_to:optional:tcp_ts=-600000
"""),
    _spec("v9", script="""
--payload=tls_client_hello
--lua-desync=hostfakesplit:host=ozon.ru:tcp_seq=0:tcp_ack=-66000:badsum
"""),
    _spec("v10", script="""
--payload=tls_client_hello
--lua-desync=fake:blob=blob_tls_clienthello_www_google_com:optional:tcp_ts=-600000:tls_mod=rnd,sni=maxcdn.bootstrapcdn.com
--lua-desync=multisplit:pos=2
"""),
)


_YOUTUBE_V = (
    _spec("Yv01", hostlist="youtube", script="""
--payload=tls_client_hello
--lua-desync=multidisorder:pos=7,sld+1:ip_autottl=2,2-12
"""),
    _spec("Yv02", hostlist="youtube", script="""
--payload=tls_client_hello
--lua-desync=multidisorder:pos=1,midsld,endhost-1:tcp_md5
"""),
    _spec("Yv03", hostlist="youtube", script="""
--payload=tls_client_hello
--lua-desync=fake:blob=0x00000000:tcp_seq=-10000:tcp_ack=-66000:repeats=2:tls_mod=rnd,dupsid,sni=www.google.com
--lua-desync=multisplit:pos=1,midsld
"""),
    _spec("Yv04", hostlist="youtube", script="""
--payload=tls_client_hello
--lua-desync=multidisorder:pos=1,midsld
"""),
    _spec("Yv05", hostlist="youtube", script="""
--payload=tls_client_hello
--lua-desync=multidisorder:pos=2,5,105,host+5,sld-1,endsld-5,endsld
"""),
    _spec("Yv06", hostlist="youtube", script="""
--payload=tls_client_hello
--lua-desync=multidisorder:pos=1,midsld
"""),
    _spec("Yv07", hostlist="youtube", script="""
--payload=tls_client_hello
--lua-desync=fake:blob=0x00000000:tcp_seq=-10000:tcp_ack=-66000
--lua-desync=fake:blob=0x0F0F0F0F:tcp_seq=-10000:tcp_ack=-66000
--lua-desync=fake:blob=blob_tls_clienthello_www_google_com:optional:tcp_seq=-10000:tcp_ack=-66000:tls_mod=rnd,dupsid,sni=fonts.google.com
--lua-desync=multidisorder:pos=10,midsld:seqovl=336:seqovl_pattern=blob_tls_clienthello_www_google_com
"""),
    _spec("Yv09", hostlist="youtube", script="""
--payload=tls_client_hello
--lua-desync=multidisorder:pos=1,sniext+1,host+1,midsld-2,midsld,midsld+2,endhost-1
"""),
    _spec("Yv10", hostlist="youtube", script="""
--payload=tls_client_hello
--lua-desync=multidisorder:pos=1,2,3,5,105,host+5,sld-1,endsld-5,endsld
"""),
    _spec("Yv11", hostlist="youtube", script="""
--payload=tls_client_hello
--lua-desync=fake:blob=0x00000000:tcp_seq=-10000:tcp_ack=-66000:repeats=2:tls_mod=rnd,dupsid,sni=www.google.com
--lua-desync=multisplit:pos=1,sniext+1,host+1,midsld-2,midsld,midsld+2,endhost-1
"""),
)


REFERENCE_STRATEGIES = (
    _spec("Discord_circular", enabled=True, filter_l7=("tls", "discord"), hostlist="discord", script="""
--payload=tls_client_hello
--in-range=-s5556
--lua-desync=circular:fails=3:maxtime=20:nld=2
--in-range=x
--lua-desync=fake:blob=fake_default_tls:tcp_flags_set=SYN:strategy=1
--lua-desync=multidisorder:pos=2,midsld:seqovl=1:seqovl_pattern=fake_default_tls:strategy=1
--lua-desync=fake:blob=fake_default_tls:badsum:tcp_seq=10000000:repeats=1:strategy=2
--lua-desync=multisplit:blob=fake_default_tls:badsum:tcp_ack=-66000:pos=2:nodrop:strategy=2:final
"""),
    _spec("discord_media", enabled=True, ports=("2053", "2083", "2087", "2096", "8443"), script="""
--lua-desync=fake:blob=blob_tls_clienthello_www_google_com:repeats=8:tcp_ts=-600000
--lua-desync=multisplit:pos=1:seqovl=681:seqovl_pattern=blob_tls_clienthello_www_google_com:repeats=8
"""),
    _spec("discord_udp", enabled=True, protocol="udp", ports=("19294-19344", "50000-50100"), filter_l7=("stun", "discord"), script="--lua-desync=fake:blob=blob_quic_initial_steamcommunity_com:repeats=6"),
    _spec("Youtube_UDP", enabled=True, protocol="udp", filter_l7=("quic",), hostlist="youtube", script="""
--payload=quic_initial
--lua-desync=fake:blob=fake_default_quic:repeats=2
"""),
    _spec("Yv08", enabled=True, hostlist="youtube", script="""
--payload=tls_client_hello
--lua-desync=hostfakesplit:host=google.com:tcp_ts=-600000
"""),
    _spec("V_circular", enabled=True, script="""
--out-range=-s34228
--payload=tls_client_hello
--in-range=-s5556
--lua-desync=circular:fails=3:maxtime=20
--in-range=x
--lua-desync=multisplit:pos=2:seqovl=681:seqovl_pattern=blob_stun:strategy=1
--lua-desync=fake:blob=blob_tls_clienthello_www_google_com:optional:tcp_ts=-600000:repeats=8:tls_mod=rnd,dupsid,sni=www.google.com:strategy=2
--lua-desync=multisplit:pos=1:seqovl=681:seqovl_pattern=blob_stun:strategy=2
--lua-desync=hostfakesplit:host=ozon.ru:tcp_ts=-600000:tcp_md5:repeats=4:strategy=3
--lua-desync=multisplit:pos=1:seqovl=582:seqovl_pattern=blob_stun:strategy=4
--lua-desync=fake:blob=blob_stun:tcp_seq=0:tcp_ack=-66000:badsum:strategy=5
--lua-desync=fakeddisorder:pos=1:pattern=blob_tls_clienthello_www_google_com:tcp_seq=0:tcp_ack=-66000:badsum:strategy=5
--lua-desync=hostfakesplit:midhost=host-2:host=i2.photo.2gis.com:tcp_seq=0:tcp_ack=-66000:badsum:strategy=6
--lua-desync=fake:blob=blob_stun:tcp_seq=-10000:tcp_ack=-66000:badsum:repeats=8:strategy=7
--lua-desync=multisplit:pos=1:seqovl=654:seqovl_pattern=blob_stun:strategy=7
--lua-desync=fake:blob=blob_tls_clienthello_www_4pda_to:optional:tcp_ts=-600000:strategy=8
--lua-desync=hostfakesplit:host=ozon.ru:tcp_seq=0:tcp_ack=-66000:badsum:strategy=9
--lua-desync=fake:blob=blob_tls_clienthello_www_google_com:optional:tcp_ts=-600000:tls_mod=rnd,sni=maxcdn.bootstrapcdn.com:strategy=10
--lua-desync=multisplit:pos=2:strategy=10:final
"""),
    _spec("games_tcp", enabled=True, ports=("2802", "2302", "2502", "3478-3480", "3724", "6000-8000", "8085", "8090", "8100", "8903", "8904", "25565", "27015-27030", "27036-27037", "50001", "60442"), filter_l7=(), script="""
--out-range=<n4
--payload=known,unknown
--lua-desync=fake:blob=blob_stun2:repeats=8:tcp_ts=-600000:payload=known,unknown
--lua-desync=fake:blob=blob_tls_clienthello_www_onetrust_com:repeats=8:tcp_ts=-600000:payload=known,unknown
--lua-desync=multisplit:pos=1:seqovl=664:seqovl_pattern=blob_tls_clienthello_www_onetrust_com:repeats=8:payload=known,unknown
"""),
    _spec("games_udp", enabled=True, protocol="udp", ports=("88", "1024-2407", "2409-4499", "4502-19293", "19345-49999", "50101-65535"), filter_l7=(), script="""
--out-range=<n4
--payload=known,unknown
--lua-desync=fake:blob=blob_quic_initial_4pda_to:repeats=10:payload=known,unknown
"""),
    _spec("Youtube_circular", hostlist="youtube", script="""
--out-range=-s34228
--payload=tls_client_hello
--in-range=-s5556
--lua-desync=circular:fails=3:maxtime=20
--in-range=x
--lua-desync=hostfakesplit:host=google.com:tcp_ts=-600000:strategy=1
--lua-desync=fake:blob=0x0F0F0F0F:tcp_seq=-10000:tcp_ack=-66000:badsum:strategy=2
--lua-desync=fake:blob=blob_tls_clienthello_www_google_com:optional:tcp_seq=-10000:tcp_ack=-66000:badsum:tls_mod=rnd,dupsid,sni=ggpht.com:strategy=2
--lua-desync=multisplit:pos=2,sld:seqovl=620:seqovl_pattern=blob_tls_clienthello_www_google_com:strategy=2
--lua-desync=multidisorder:pos=1,midsld:strategy=3
--lua-desync=tls_client_hello_clone:blob=cloned_tls:fallback=fake_default_tls:strategy=4
--lua-desync=fake:blob=cloned_tls:optional:tcp_seq=10000000:tcp_ack=-66000:repeats=2:tls_mod=rnd,dupsid,sni=fonts.google.com:strategy=4
--lua-desync=multidisorder:pos=1:seqovl=681:seqovl_pattern=blob_tls_clienthello_www_google_com:strategy=4
--lua-desync=fake:blob=0x00000000:tcp_seq=-10000:tcp_ack=-66000:strategy=5
--lua-desync=fake:blob=0x0F0F0F0F:tcp_seq=-10000:tcp_ack=-66000:strategy=5
--lua-desync=fake:blob=blob_tls_clienthello_www_google_com:optional:tcp_seq=-10000:tcp_ack=-66000:tls_mod=rnd,dupsid,sni=fonts.google.com:strategy=5
--lua-desync=multidisorder:pos=10,midsld:seqovl=336:seqovl_pattern=blob_tls_clienthello_www_google_com:strategy=5
--lua-desync=multisplit:pos=1,sniext+1:seqovl=1:strategy=6
--lua-desync=fakeddisorder:pos=method+2:tcp_md5:strategy=7
--lua-desync=tls_client_hello_clone:blob=cloned_tls:fallback=fake_default_tls:strategy=8
--lua-desync=fake:blob=cloned_tls:optional:tcp_ts=-600000:tls_mod=rnd,dupsid,sni=www.google.com:strategy=8
--lua-desync=hostfakesplit:ip_id=zero:host=www.google.com:altorder=1:tcp_ts=-600000:strategy=8
--lua-desync=hostfakesplit:host=google.com:tcp_ts=-600000:strategy=9
--lua-desync=fake:blob=blob_tls_clienthello_www_google_com:optional:tcp_ts=-600000:repeats=6:strategy=10
--lua-desync=fakedsplit:ip_id=zero:pattern=0x00:tcp_ts=-600000:strategy=10
--lua-desync=fake:blob=blob_tls_clienthello_www_google_com:optional:tcp_ts=-600000:repeats=8:strategy=11
--lua-desync=multisplit:pos=1:seqovl=681:seqovl_pattern=blob_tls_clienthello_www_google_com:ip_id=zero:strategy=11
--lua-desync=multisplit:pos=1:seqovl=681:seqovl_pattern=blob_tls_clienthello_www_google_com:ip_id=zero:strategy=12
--lua-desync=multisplit:pos=1,sniext+1:seqovl=1:strategy=13
--lua-desync=multisplit:seqovl=681:seqovl_pattern=blob_tls_clienthello_www_google_com:strategy=14
--lua-desync=fake:blob=blob_tls_clienthello_www_google_com:optional:tcp_seq=0:tcp_ack=-66000:badsum:tls_mod=rnd,dupsid,sni=fonts.google.com:strategy=15
--lua-desync=fake:blob=0x0F0F0F0F:tcp_seq=0:tcp_ack=-66000:badsum:tls_mod=none:strategy=15
--lua-desync=fakeddisorder:pos=10,midsld:seqovl=336:seqovl_pattern=blob_tls_clienthello_gosuslugi_ru:pattern=blob_tls_clienthello_vk_com:tcp_seq=0:tcp_ack=-66000:badsum:strategy=15
--lua-desync=multidisorder:pos=7,sld+1:nodrop:strategy=16
--lua-desync=multidisorder:pos=1,midsld,endhost-1:strategy=17
--lua-desync=fake:blob=0x00000000:tcp_seq=-10000:tcp_ack=-66000:repeats=2:strategy=18
--lua-desync=fake:blob=fake_default_tls:tcp_seq=-10000:tcp_ack=-66000:repeats=2:tls_mod=rnd,dupsid,sni=www.google.com:strategy=18
--lua-desync=multisplit:pos=1,midsld:strategy=18
--lua-desync=multidisorder:pos=1,midsld:strategy=19
--lua-desync=multisplit:pos=1,2:seqovl=4:seqovl_pattern=blob_tls_clienthello_www_google_com:strategy=20
--lua-desync=multidisorder:pos=2,5,105,host+5,sld-1,endsld-5,endsld:strategy=21
--lua-desync=fake:blob=0x0F0F0F0F:tcp_seq=-10000:tcp_ack=-66000:badsum:strategy=22
--lua-desync=fake:blob=blob_tls_clienthello_www_google_com:optional:tcp_seq=-10000:tcp_ack=-66000:badsum:tls_mod=rnd,dupsid,sni=ggpht.com:strategy=22
--lua-desync=multisplit:pos=2,sld:seqovl=2108:seqovl_pattern=blob_tls_clienthello_www_google_com:strategy=22:final
"""),
    _spec("Yv_circular", hostlist="youtube", script="""
--out-range=-s34228
--payload=tls_client_hello
--in-range=-s5556
--lua-desync=circular:fails=3:maxtime=20
--in-range=x
--lua-desync=multidisorder:pos=7,sld+1:ip_autottl=2,2-12:strategy=1
--lua-desync=multidisorder:pos=1,midsld,endhost-1:tcp_md5:strategy=2
--lua-desync=fake:blob=0x00000000:tcp_seq=-10000:tcp_ack=-66000:repeats=2:tls_mod=rnd,dupsid,sni=www.google.com:strategy=3
--lua-desync=multisplit:pos=1,midsld:strategy=3
--lua-desync=multidisorder:pos=1,midsld:strategy=4
--lua-desync=multidisorder:pos=2,5,105,host+5,sld-1,endsld-5,endsld:strategy=5
--lua-desync=multidisorder:pos=1,midsld:strategy=6
--lua-desync=fake:blob=0x00000000:tcp_seq=-10000:tcp_ack=-66000:strategy=7
--lua-desync=fake:blob=0x0F0F0F0F:tcp_seq=-10000:tcp_ack=-66000:strategy=7
--lua-desync=fake:blob=blob_tls_clienthello_www_google_com:optional:tcp_seq=-10000:tcp_ack=-66000:tls_mod=rnd,dupsid,sni=fonts.google.com:strategy=7
--lua-desync=multidisorder:pos=10,midsld:seqovl=336:seqovl_pattern=blob_tls_clienthello_www_google_com:strategy=7
--lua-desync=hostfakesplit:host=google.com:tcp_ts=-600000:strategy=8
--lua-desync=multidisorder:pos=1,sniext+1,host+1,midsld-2,midsld,midsld+2,endhost-1:strategy=9
--lua-desync=multidisorder:pos=1,2,3,5,105,host+5,sld-1,endsld-5,endsld:strategy=10
--lua-desync=fake:blob=0x00000000:tcp_seq=-10000:tcp_ack=-66000:repeats=2:tls_mod=rnd,dupsid,sni=www.google.com:strategy=11
--lua-desync=multisplit:pos=1,sniext+1,host+1,midsld-2,midsld,midsld+2,endhost-1:strategy=11:final
"""),
    _spec("Routerich_circular", script="""
--out-range=-s34228
--payload=tls_client_hello
--in-range=-s5556
--lua-desync=circular:fails=3:maxtime=20
--in-range=x
--lua-desync=hostfakesplit:midhost=host-2:host=rzd.ru:tcp_seq=0:tcp_ack=-66000:badsum:strategy=1
--lua-desync=multisplit:seqovl=681:seqovl_pattern=blob_stun:strategy=2
--lua-desync=fake:blob=blob_tls_clienthello_www_google_com:optional:tcp_seq=0:tcp_ack=-66000:badsum:tls_mod=rnd,dupsid,sni=fonts.google.com:strategy=3
--lua-desync=fake:blob=0x0F0F0F0F:tcp_seq=0:tcp_ack=-66000:badsum:tls_mod=none:strategy=3
--lua-desync=fakeddisorder:pos=10,midsld:seqovl=336:seqovl_pattern=blob_tls_clienthello_gosuslugi_ru:pattern=blob_tls_clienthello_vk_com:tcp_seq=0:tcp_ack=-66000:badsum:strategy=3
--lua-desync=fake:blob=blob_tls_clienthello_t2_ru:optional:tcp_seq=0:tcp_ack=-66000:badsum:tls_mod=rnd,dupsid,sni=m.ok.ru:strategy=4
--lua-desync=fake:blob=0x0F0F0F0F:tcp_seq=0:tcp_ack=-66000:badsum:tls_mod=none:strategy=4
--lua-desync=fakeddisorder:pos=10,midsld:seqovl=336:seqovl_pattern=blob_tls_clienthello_gosuslugi_ru:pattern=blob_tls_clienthello_vk_com:tcp_seq=0:tcp_ack=-66000:badsum:strategy=4
--lua-desync=fake:blob=0x0F0F0F0F:tcp_seq=-10000:tcp_ack=-66000:strategy=5
--lua-desync=fake:blob=blob_tls_clienthello_www_google_com:optional:tcp_seq=-10000:tcp_ack=-66000:tls_mod=rnd,dupsid,sni=google.com:strategy=5
--lua-desync=multisplit:pos=2,sld:seqovl=2108:seqovl_pattern=blob_tls_clienthello_www_google_com:strategy=5
--lua-desync=fake:blob=blob_stun:optional:tcp_seq=0:tcp_ack=-66000:badsum:tls_mod=none:strategy=6
--lua-desync=fakeddisorder:pos=1:pattern=blob_tls_clienthello_www_google_com:tcp_seq=0:tcp_ack=-66000:badsum:strategy=6
--lua-desync=multisplit:pos=1,sniext+1:seqovl=1:strategy=7
--lua-desync=fake:blob=0x0F0F0F0F:tcp_seq=-10000:tcp_ack=-66000:badsum:strategy=8
--lua-desync=fake:blob=blob_tls_clienthello_www_google_com:optional:tcp_seq=-10000:tcp_ack=-66000:badsum:tls_mod=rnd,dupsid,sni=ggpht.com:strategy=8
--lua-desync=multisplit:pos=2,sld:seqovl=620:seqovl_pattern=blob_tls_clienthello_www_google_com:strategy=8
--lua-desync=hostfakesplit:host=mapgl.2gis.com:tcp_seq=0:tcp_ack=-66000:badsum:strategy=9
--lua-desync=fake:blob=blob_tls_clienthello_www_4pda_to:optional:tcp_ts=-600000:tls_mod=none:strategy=10
--lua-desync=fake:blob=blob_stun:optional:tcp_seq=0:tcp_ack=-66000:badsum:strategy=11
--lua-desync=multisplit:pos=1:seqovl=654:seqovl_pattern=blob_stun:strategy=11
--lua-desync=hostfakesplit:midhost=host-2:host=i2.photo.2gis.com:tcp_seq=0:tcp_ack=-66000:badsum:strategy=12
--lua-desync=multisplit:pos=1:seqovl=582:seqovl_pattern=blob_stun:strategy=13:final
"""),
    _spec("DoH_DNS", protocol="udp", ports=("53",), filter_l7=("unknown", "dns"), script="""
--out-range=-n2
--lua-desync=fake:blob=quic_initial_www_google_com:repeats=4
"""),
    _spec("DoH_TLS", ports=("853",), script="""
--hostlist-domains=dns.adguard-dns.com,cloudflare-dns.com,one.one.one.one,dns.alidns.com,dns.quad9.net
--lua-desync=multisplit:seqovl=8:seqovl_pattern=0x000100502112A442
"""),
    *_BASE_V,
    _spec("alt11", ports=("80", "443"), filter_l7=(), script="""
--lua-desync=fake:blob=blob_stun2:repeats=8:tcp_ts=-600000
--lua-desync=fake:blob=blob_tls_clienthello_www_onetrust_com:repeats=8:tcp_ts=-600000
--lua-desync=multisplit:pos=1:seqovl=664:seqovl_pattern=blob_tls_clienthello_www_onetrust_com:repeats=8
"""),
    *_YOUTUBE_V,
)
