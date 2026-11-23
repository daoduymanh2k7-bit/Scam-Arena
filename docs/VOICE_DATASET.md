# Personal voice dataset collection

Open `/voice-training.html` from the signed-in account controls. Users can record
read prompts or spontaneous speech, listen locally, explicitly consent, and save.
Recording ends automatically at about 14 seconds, below the server's 15-second
limit. The server decodes and validates 1–15 seconds of mono 16-kHz PCM16 WAV.
Only a Save action uploads audio; closing an unsaved recording stops its tracks.

Users manually correct transcripts and mark samples pending, confirmed, or needing
a retake. The machine transcript remains separate. Confirmation does not train or
activate a personal model. There is no automatic training, export, or retention of
call recordings in this first release. No collection request enters the dialogue,
Rasa, scoring, or LLM memory pipelines. Account IDs come from authenticated cookies.

Audio and metadata live in `voice_samples` in PostgreSQL, with cascading account
deletion. Every read/update/delete filters by owner, including audio playback.
At most 200 samples per account (about 96 MB of PCM at the maximum duration) are
stored. Database backups contain these recordings; deleting a live row does not
erase previously made backups. Treat backup retention accordingly. Models and
datasets are not published to GitHub. A later training feature should split by
recording session, retain an independent evaluation set, and support rollback.

Recognition is optional and manual. The sample acquires a scheduler slot only
when no call recognition is running or queued, and never joins the call queue.
There is no GPU training or new worker loop. Already running inference cannot
be interrupted: a call arriving after a sample starts may wait for it to finish.
No database connection is held during inference. Optimistic revision checks reject
stale edits and results arriving after an edit or deletion. Users can transcribe
by hand when the model is busy or unavailable. CPU decoding of sample uploads can
still consume resources; this is not a zero-overhead guarantee.
