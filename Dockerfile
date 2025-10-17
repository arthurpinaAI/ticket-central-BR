FROM baserow/baserow:1.25.2
# Overwrite Caddyfile to force IPv4 upstreams
COPY caddy/Caddyfile /baserow/caddy/Caddyfile
