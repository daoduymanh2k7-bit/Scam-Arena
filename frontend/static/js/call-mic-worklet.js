class CallMicProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.enabled = false;
    this.cycle = 0;
    this.noise = 0.004;
    this.reset();
    this.port.onmessage = ({ data }) => {
      this.enabled = data.enabled;
      this.cycle = data.cycle;
      this.reset();
    };
  }

  reset() {
    this.preRoll = [];
    this.preRollSize = 0;
    this.onset = 0;
    this.clip = null;
    this.clipSize = 0;
    this.voiced = 0;
    this.quiet = 0;
  }

  process(inputs) {
    const samples = inputs[0]?.[0];
    if (!this.enabled || !samples?.length) return true;

    let power = 0;
    for (const sample of samples) power += sample * sample;
    const level = Math.sqrt(power / samples.length);
    const threshold = Math.max(0.01, this.noise * 3);
    const frame = new Float32Array(samples);

    if (!this.clip) {
      this.preRoll.push(frame);
      this.preRollSize += frame.length;
      while (this.preRollSize > sampleRate * .24) this.preRollSize -= this.preRoll.shift().length;
      if (level < threshold) {
        this.noise = this.noise * .98 + Math.min(level, .014) * .02;
        this.onset = 0;
      } else {
        this.onset += frame.length;
      }
      if (this.onset >= sampleRate * .045) {
        this.clip = this.preRoll;
        this.clipSize = this.preRollSize;
        this.voiced = this.onset;
        this.port.postMessage({ type: "speech-start", cycle: this.cycle });
      }
      return true;
    }

    this.clip.push(frame);
    this.clipSize += frame.length;
    if (level >= threshold * .7) {
      this.quiet = 0;
      this.voiced += frame.length;
    } else {
      this.quiet += frame.length;
    }
    if (this.quiet < sampleRate * .75 && this.clipSize < sampleRate * 14) return true;

    if (this.voiced >= sampleRate * .085) {
      const result = new Float32Array(this.clipSize);
      let position = 0;
      for (const chunk of this.clip) {
        result.set(chunk, position);
        position += chunk.length;
      }
      this.enabled = false;
      this.port.postMessage({ type: "speech", cycle: this.cycle, samples: result, rate: sampleRate }, [result.buffer]);
    } else {
      this.port.postMessage({ type: "noise", cycle: this.cycle });
    }
    this.reset();
    return true;
  }
}

registerProcessor("scam-arena-call-mic", CallMicProcessor);
