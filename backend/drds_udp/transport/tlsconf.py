"""TLS (stdlib ssl) and DTLS (pyOpenSSL) context builders."""

from __future__ import annotations

import ssl

from .base import TlsOptions, TransportError


def make_ssl_context(opts: TlsOptions) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if opts.verify:
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.check_hostname = bool(opts.server_name)
        if opts.ca_file:
            ctx.load_verify_locations(cafile=opts.ca_file)
        else:
            ctx.load_default_certs()
    else:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    if opts.cert_file:
        ctx.load_cert_chain(opts.cert_file, opts.key_file or None)
    if opts.ciphers:
        ctx.set_ciphers(opts.ciphers)
    return ctx


def make_dtls_context(opts: TlsOptions, server: bool = False):
    try:
        from OpenSSL import SSL
    except ImportError as exc:  # pragma: no cover
        raise TransportError("DTLS needs pyOpenSSL: pip install pyOpenSSL") from exc

    ctx = SSL.Context(SSL.DTLS_SERVER_METHOD if server else SSL.DTLS_CLIENT_METHOD)
    # memory BIOs cannot query the path MTU -> we set it on the connection instead
    ctx.set_options(SSL.OP_NO_QUERY_MTU)
    if not server:
        if opts.verify:
            ctx.set_verify(SSL.VERIFY_PEER, lambda conn, cert, errnum, depth, ok: bool(ok))
            if opts.ca_file:
                ctx.load_verify_locations(opts.ca_file)
            else:
                ctx.set_default_verify_paths()
        else:
            ctx.set_verify(SSL.VERIFY_NONE, lambda *a: True)
    if opts.cert_file:
        ctx.use_certificate_chain_file(opts.cert_file)
        ctx.use_privatekey_file(opts.key_file or opts.cert_file)
    if opts.ciphers:
        ctx.set_cipher_list(opts.ciphers.encode())
    return ctx


def ssl_error_text(exc: BaseException) -> str:
    """Flatten pyOpenSSL's nested error tuples into something readable."""
    args = getattr(exc, "args", ())
    if args and isinstance(args[0], list):
        parts = []
        for item in args[0]:
            if isinstance(item, tuple):
                parts.append(":".join(str(x) for x in item if x))
            else:
                parts.append(str(item))
        if parts:
            return "; ".join(parts)
    return str(exc) or exc.__class__.__name__
