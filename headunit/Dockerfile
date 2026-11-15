# OpenAuto (opencardev) Android Auto head unit emulator, x86_64 desktop build.
# Build context: this directory. Sources come from ./src/aasdk (branch newdev)
# and ./src/openauto (branch main), cloned by build.sh.
FROM debian:trixie

ARG DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates git build-essential cmake ninja-build pkg-config file lsb-release \
      libboost-all-dev libprotobuf-dev protobuf-compiler libabsl-dev \
      libusb-1.0-0-dev libssl-dev libblkid-dev libgps-dev libtag1-dev librtaudio-dev \
      qtbase5-dev qtmultimedia5-dev qttools5-dev qttools5-dev-tools qtconnectivity5-dev \
      libqt5multimedia5-plugins gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
      gstreamer1.0-plugins-bad gstreamer1.0-libav gstreamer1.0-pulseaudio \
      libpulse0 pulseaudio-utils libasound2-plugins alsa-utils \
      fonts-dejavu-core x11-apps imagemagick usbutils procps \
    && rm -rf /var/lib/apt/lists/*

# --- aasdk ---
COPY src/aasdk /build/aasdk
RUN cd /build/aasdk && cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DAASDK_TEST=OFF -DSKIP_BUILD_PROTOBUF=ON -DSKIP_BUILD_ABSL=ON \
      -DCMAKE_INSTALL_PREFIX=/usr/local \
 && cmake --build build --parallel \
 && cmake --install build && ldconfig

# --- openauto ---
COPY src/openauto /build/openauto
RUN cd /build/openauto && cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DNOPI=ON \
 && cmake --build build --parallel \
 && install -m755 build/bin/autoapp /usr/local/bin/autoapp \
 && (install -m755 build/bin/btservice /usr/local/bin/btservice || true) \
 && ldconfig

# Runtime user matching the host user so the X/Pulse sockets and config dir work.
ARG UID=1000
ARG GID=1000
# Video sinks and tools for the Qt/GStreamer player (without these the player fails with
# "GStreamer encountered a general resource error" and the projection stays black).
RUN apt-get update && apt-get install -y --no-install-recommends \
        gstreamer1.0-x gstreamer1.0-gl gstreamer1.0-tools gstreamer1.0-pulseaudio \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g ${GID} hu 2>/dev/null || true \
 && useradd -m -u ${UID} -g ${GID} -G plugdev,video,audio hu \
 && mkdir -p /home/hu/openauto && chown ${UID}:${GID} /home/hu/openauto \
 && touch /etc/button_wifi_visible
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
USER hu
WORKDIR /home/hu/openauto
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/usr/local/bin/autoapp"]
