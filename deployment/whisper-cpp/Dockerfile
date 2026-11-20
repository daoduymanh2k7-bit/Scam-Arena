FROM debian:bookworm-slim AS build
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl cmake build-essential \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
# whisper.cpp v1.8.4, pinned to a reviewed source revision.
RUN curl -fL --retry 3 https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/9386f239401074690479731c1e41683fbbeac557 \
    | tar -xz --strip-components=1
# Runtime CPU dispatch: do not compile only for the build machine's CPU.
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
      -DGGML_NATIVE=OFF -DGGML_BACKEND_DL=ON -DGGML_CPU_ALL_VARIANTS=ON \
      -DWHISPER_BUILD_TESTS=OFF -DWHISPER_CURL=OFF \
      -DWHISPER_ALL_WARNINGS=OFF -DGGML_ALL_WARNINGS=OFF \
    && (cmake --build build --parallel 2 > /tmp/build.log 2>&1 || (tail -n 80 /tmp/build.log; exit 1)) \
    && cmake --install build --prefix /opt/whisper

FROM debian:bookworm-slim AS model
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
ARG WHISPER_CPP_MODEL=base-q8_0
RUN case "$WHISPER_CPP_MODEL" in \
      base-q8_0) checksum=c577b9a86e7e048a0b7eada054f4dd79a56bbfa911fbdacf900ac5b567cbb7d9 ;; \
      base-q5_1) checksum=422f1ae452ade6f30a004d7e5c6a43195e4433bc370bf23fac9cc591f01a8898 ;; \
      *) echo 'Supported multilingual models: base-q8_0, base-q5_1' >&2; exit 1 ;; \
    esac \
    && mkdir /models \
    && curl -fL --retry 3 --connect-timeout 20 --max-time 900 \
      "https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-${WHISPER_CPP_MODEL}.bin" \
      -o /models/model.bin \
    && echo "$checksum  /models/model.bin" | sha256sum -c - \
    && printf '%s\n' "$WHISPER_CPP_MODEL" > /models/model-name

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system speech \
    && useradd --system --gid speech --home-dir /tmp speech
COPY --from=build /opt/whisper /opt/whisper
COPY --from=build /src/LICENSE /opt/whisper/LICENSE
COPY --from=model /models /models
ENV LD_LIBRARY_PATH=/opt/whisper/lib
USER speech
WORKDIR /tmp
EXPOSE 8080
ENTRYPOINT ["/opt/whisper/bin/whisper-server"]
