#!/usr/bin/env bash
# Private preview CA + server certificate for the phone preview (docs/72).
#
#   tools/preview/make_cert.sh <out-dir> <ip-or-hostname>...
#
# The CA is *name-constrained* to exactly the listed IPs / host names: even if
# its key leaked, a phone that trusts it cannot be fooled for any other site.
# Re-running keeps an existing CA (phones stay trusted) and re-issues the
# server certificate, e.g. after the VPN address changed.
set -euo pipefail
out=${1:?usage: make_cert.sh <out-dir> <ip-or-host>...}
shift
[ "$#" -gt 0 ] || { echo "need at least one IP or host name" >&2; exit 2; }
mkdir -p "$out"
chmod 700 "$out"
cd "$out"
umask 077

san=() constraints=()
for name in "$@"; do
  if [[ $name =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    san+=("IP:$name"); constraints+=("permitted;IP:$name/255.255.255.255")
  else
    san+=("DNS:$name"); constraints+=("permitted;DNS:$name")
  fi
done
join() { local IFS=,; echo "$*"; }

if [ ! -s ca.key ] || [ ! -s ca.crt ]; then
  openssl req -x509 -new -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
    -keyout ca.key -out ca.crt -days 3650 -sha256 \
    -subj "/O=PokeTactics preview/CN=PokeTactics Preview CA ($(hostname -s))" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "nameConstraints=critical,$(join "${constraints[@]}")" \
    -addext "subjectKeyIdentifier=hash"
  echo "created CA: $out/ca.crt (constrained to: $*)"
else
  echo "keeping existing CA: $out/ca.crt"
fi

openssl req -new -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
  -keyout server.key -out server.csr -subj "/O=PokeTactics preview/CN=PokeTactics preview server" 2>/dev/null
cat > server.ext <<EXT
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature
extendedKeyUsage=serverAuth
subjectAltName=$(join "${san[@]}")
authorityKeyIdentifier=keyid
EXT
# 397 days: within the limits Chrome and iOS place on TLS server certificates.
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days 397 -sha256 -extfile server.ext 2>/dev/null
cat server.crt ca.crt > server-chain.crt
chmod 644 ca.crt server.crt server-chain.crt
rm -f server.csr server.ext
openssl verify -CAfile ca.crt server.crt
echo "server certificate for: $*"
