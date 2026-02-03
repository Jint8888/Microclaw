# Use the pre-built base image for A0
# FROM agent-zero-base:local
FROM agent0ai/agent-zero-base:latest

# Check if the argument is provided, else throw an error
ARG BRANCH
RUN if [ -z "$BRANCH" ]; then echo "ERROR: BRANCH is not set!" >&2; exit 1; fi
ENV BRANCH=$BRANCH

# Copy filesystem files to root
COPY ./docker/run/fs/ /

# Copy source code to /git/agent-zero
COPY . /git/agent-zero

# Fix Windows line endings (CRLF -> LF) for all shell scripts
RUN find /ins /exe -type f -name "*.sh" -exec sed -i 's/\r$//' {} \; 2>/dev/null || true

# pre installation steps
RUN bash /ins/pre_install.sh $BRANCH

# install A0
RUN bash /ins/install_A0.sh $BRANCH

# install additional software
RUN bash /ins/install_additional.sh $BRANCH

# cleanup repo and install A0 without caching, this speeds up builds
ARG CACHE_DATE=none
RUN echo "cache buster $CACHE_DATE" && bash /ins/install_A02.sh $BRANCH

# post installation steps
RUN bash /ins/post_install.sh $BRANCH

# Expose ports
# - 22: SSH
# - 80: Web UI
# - 50002: Gateway API (Telegram, Discord, Email channels)
# - 9000-9009: Additional services
EXPOSE 22 80 50002 9000-9009

RUN chmod +x /exe/initialize.sh /exe/run_A0.sh /exe/run_tunnel_api.sh

# initialize runtime and switch to supervisord
CMD ["/exe/initialize.sh", "$BRANCH"]
