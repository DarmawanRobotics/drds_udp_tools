"""TLS (stdlib ssl) and DTLS (pyOpenSSL) context builders."""

from __future__ import annotations

import ssl

from .base import TlsOptions, TransportError

COMPAT_CIPHERS = "DEFAULT:@SECLEVEL=0"

_PLAIN_PEER = ("wrong version number", "record layer failure", "packet length too long", "unexpected record",
               "http request", "record_layer_failure", "bad record", "decode error", "unexpected message")
_POLICY = ("unsupported protocol", "protocol version", "no protocols available", "no ciphers available",
           "insufficient security", "dh key too small", "ee key too small", "ca md too weak")
_CLIENT_CERT_MISSING = ("certificate required", "peer did not return a certificate")
_CLIENT_CERT_REJECTED = ("unknown ca", "bad certificate", "certificate unknown", "unsupported certificate",
                         "certificate expired", "certificate revoked", "access denied")
_VERIFY_FAILED = ("certificate verify failed",)

CLIENT_CERT_HINT = ("the robot requires a client certificate (mutual TLS): set Client certificate + key in the "
                    "connection settings (CLI: --cert/--key) — the files come from Deep Robotics")


def handshake_hint(text: str, plain_name: str, client_cert: bool = False) -> str:
    """Turn an OpenSSL error into the next thing to try in the field.

    `client_cert`: whether we presented a client certificate (changes what a bare "handshake failure" means).
    """
    t = text.lower()
    if any(k in t for k in _CLIENT_CERT_MISSING):
        return f" — {CLIENT_CERT_HINT}"
    if any(k in t for k in _VERIFY_FAILED):
        return " — the robot's certificate did not verify: turn certificate verification off or set the right CA file"
    if client_cert and any(k in t for k in _CLIENT_CERT_REJECTED):
        return " — the robot rejected our client certificate: check that cert and key are the pair Deep Robotics gave you"
    if any(k in t for k in _PLAIN_PEER):
        return f" — the port answered with something that is not {plain_name.upper()}-encrypted: it is probably a plain port"
    if "handshake failure" in t and not client_cert:
        # DTLS 1.2 / TLS 1.2 servers send a bare handshake_failure alert when a required client cert is missing
        return (f" — {CLIENT_CERT_HINT}; if it still fails with the certificate, enable compat mode "
                "(old TLS/DTLS versions, weak ciphers)")
    if "handshake failure" in t or any(k in t for k in _POLICY):
        return " — protocol/cipher mismatch: enable compat mode (old TLS/DTLS versions, weak ciphers) and retry"
    return ""


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
    if opts.compat:
        try:
            ctx.minimum_version = ssl.TLSVersion.TLSv1
        except (ValueError, AttributeError):
            pass
        ctx.set_ciphers(opts.ciphers or COMPAT_CIPHERS)
    elif opts.ciphers:
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
    if opts.compat:
        ctx.set_cipher_list((opts.ciphers or COMPAT_CIPHERS).encode())
    elif opts.ciphers:
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
