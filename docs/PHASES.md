# Build phases and your manual steps

Scope comes from `SDE_Intern_Round1_Assignment.pdf`. We are completing one phase at a time. Phase 1 is complete. Phase 2 spoken booking is verified; spoken cancellation and phone correction remain for manual verification. Phase 3 frontend implementation is complete and ready for your listening and usability check.

| Phase | What will be built | What you do manually | Done when |
| --- | --- | --- | --- |
| 1 — Foundation | Local app, mock doctors and slots, SQLite, appointment rules, dashboard preview, tests | Open the dashboard and check the layout. No keys required. | App starts; availability, booking, cancellation, and persistence checks pass. |
| 2 — Voice agent | Pipecat audio pipeline, ElevenLabs STT/TTS, Gemini function calling, spoken phone confirmation, WebRTC and VAD | Create provider accounts/keys, add secrets to local `.env`, select a voice, allow microphone access, make a test call. | A real call checks availability, books, and cancels using the spoken confirmed number. |
| 3 — Call dashboard | Start/end/mute, call states/timer, live transcript, appointment refresh, phone-style panel and responsive polish | Test with your microphone and speakers/headphones; try a narrow browser window; give feedback on voice and wording. | Call state and transcript match the actual conversation; booking/cancellation appears on the dashboard. |
| 4 — Verification and submission | Edge-case fixes, complete README, explanation notes, final checks, demo rehearsal | Record the video, review your code explanation, create/publish the GitHub repository under your account, and submit the links through the form. | All required flows work and the repository/video/description are submitted. |

## Phase 1 — do now

1. Open PowerShell in `E:\nexovai`.
2. Run `.\setup.cmd` if dependencies have not already been installed. It creates a local Python environment and installs packages; no API accounts are involved.
3. Run `.\run.cmd` and leave the terminal open.
4. Open **http://127.0.0.1:8000**. You should see four doctors, a date picker, and the appointments area. If today has no remaining slots, choose tomorrow.
5. Change the date and specialty filter. Confirm the layout looks right on your screen.
6. Optionally inspect **http://127.0.0.1:8000/docs** and use the example booking/cancellation requests in the README. The automated tests already cover this backend flow.

No microphone permission, API key, payment, deployment, or GitHub setup is required for the Phase 1 dashboard. Voice remains disabled until the Phase 2 prerequisites are present.

## Phase 2 — prepare accounts and credentials

**Current status (25 November 2026):** the Pipecat pipeline, four function tools, phone-confirmation state, WebRTC routes, and basic call/transcript/mute/end controls are implemented. Voice dependencies are installed, all three credential settings are present locally, and all 54 tests pass, including Pipecat imports and the Silero model check. The app starts successfully. Voice-list access now works. The built-in Adam voice passed speech generation on the current free account and is saved locally. A live WebRTC check delivered greeting audio, transcribed a synthetic spoken doctor question through ElevenLabs, and returned Gemini's response as audio. No provider error occurred and the test call cleaned up successfully. The user has now confirmed the laptop microphone works and made an appointment; the booking was verified as saved through the API. Current manual step: test spoken cancellation and the phone-correction case in steps 8-9 before marking this phase done.

Browser checks now also passed a real provider-backed question and spoken reply using a synthetic microphone. The microphone selector, server input meter, silent-input warning, mute/unmute, device switching, cleanup, and mobile panel passed. Cached JavaScript/CSS could leave new controls inactive; content-versioned asset URLs and cache headers now keep the page and controls in sync. The local user call subsequently received microphone audio and finalized transcripts. Spoken booking is now verified. Spoken cancellation and phone correction remain outstanding.

These account actions need you because they involve your logins, provider terms, and private credentials.

1. Sign in to [ElevenLabs](https://elevenlabs.io/). Create an API key with access to speech-to-text and text-to-speech. Confirm your account has access and quota for the selected speech models; we will check the precise models when wiring the pipeline.
2. Choose a voice available to your account and copy its voice ID. Voice choice is yours; no voice cloning is required.
3. Create a Gemini API key in [Google AI Studio](https://aistudio.google.com/apikey). Check the quota available to your account. Free quota availability is provider-dependent; do not assume unlimited usage. [Official key setup](https://ai.google.dev/gemini-api/docs/api-key).
4. Create the local secrets file once (do not overwrite an existing one):

   ```powershell
   if (-not (Test-Path .env)) { Copy-Item .env.example .env }
   notepad .env
   ```

5. Fill `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, and `GOOGLE_API_KEY`. All three values have been saved locally; do not overwrite them unless replacing a key or voice. The default `GEMINI_MODEL` is `gemini-3.5-flash-lite`, including when the setting is blank. Verify that your Google project can use it. Save `.env`; do not paste keys into chat or commit them. Rotate any key that has been shared and replace its value locally.
6. From `E:\nexovai`, install the voice dependencies and check configuration:

   ```powershell
   .\setup-voice.cmd
   .\.venv\Scripts\python.exe -m scripts.check_voice --providers
   ```

   These commands require internet access. The checker prints status only, never secrets. Read-only provider checks do not guarantee generation/speech quota. If installation or the import check fails, keep the error text for troubleshooting, excluding any credentials.
7. Stop any running server with Ctrl+C, then run `.\run.cmd` again. Open **http://127.0.0.1:8000** on the same machine. The call button enables when the dependencies and all three settings are present. Allow microphone access in Chrome or Edge. Select your laptop microphone in the call panel and confirm the input meter moves while you speak. Use headphones if speaker audio is picked up by the microphone.
8. Test a spoken booking and cancellation in one call. Say the phone number one digit at a time. Wait until the full readback ends, then say **yes** or **no**. After a successful booking, a cancellation requires a fresh readback. Check that the dashboard updates for both actions.
9. Test a correction: interrupt or reject an incorrect number, then provide the correct number. No mutation should occur until the correct number has been fully read back and confirmed. Use a fictional number for testing.

### Free-plan voice troubleshooting

- A voice preview working on the ElevenLabs website does not prove API access. Library voices are unavailable through the API on the free plan; some voices require Creator tier or above. [Voice Library documentation](https://elevenlabs.io/docs/eleven-creative/voices/voice-library/).
- For account voice discovery, open Developers > API Keys > the existing key's three-dot menu > Edit, set Voices to Read, and save. Keep Text to Speech and Speech to Text enabled. [Key permissions](https://elevenlabs.io/docs/help-center/technical/how-do-i-authorize-myself-using-an-api-key).
- The free plan includes three custom Voice Design slots. If there is no eligible saved voice, use Voices > My Voices > Add a new voice > Voice Design to create one, then copy its voice ID. We still need to test that voice with the configured speech model. [Free-plan slots](https://elevenlabs.io/docs/overview/administration/billing), [Voice Design](https://elevenlabs.io/docs/eleven-creative/voices/voice-design).
- Test a candidate without changing the saved voice: `.\.venv\Scripts\python.exe -m scripts.check_voice --speech --voice-id VOICE_ID`. This generates one short greeting using a small amount of speech quota. A successful speech check is required before selecting the replacement.

Implementation reference: the code uses Pipecat's streaming [ElevenLabs STT service](https://docs.pipecat.ai/api-reference/server/services/stt/elevenlabs), [SmallWebRTCTransport](https://docs.pipecat.ai/api-reference/server/services/transport/small-webrtc), Gemini function calling, ElevenLabs streaming TTS, and Silero VAD. The model default is documented by [Google](https://aistudio.google.com/docs/models/gemini-3.5-flash-lite). Browser speech synthesis and canned conversations are not used. The Phase 3 phone-style screen now wraps the same working WebRTC and microphone connection.

## Phase 3 — manually test the call experience

**Implemented (25 November 2026):** a phone-style call screen with Aster's identity, connecting/connected/ended states, an elapsed call timer, live transcript bubbles, mute/end/retry controls, and a collapsible microphone selector. The waveform measures microphone sound received by the server and the assistant's incoming audio. Soft ringing and hang-up sounds can be toggled with the speaker button. A confirmed booking or cancellation displays a card inside the phone; the changed appointment row and doctor's card are highlighted on the dashboard. The layout adapts to narrow and landscape screens and respects reduced-motion settings.

**Validation:** 54 backend tests pass. A real browser call with a synthetic spoken question passed ElevenLabs transcription, Gemini response, and spoken playback with the new timer and waveform. Browser checks also passed microphone switching, mute/unmute, silence detection, cleanup, denied permission, provider failure, retry, and ending during a pending permission request. Simulated server events verified booking/cancellation cards, dashboard highlights and focus, sound generation/toggle, frozen/reset timers, and 390px, 320px, and landscape layouts. Those visual checks did not create or cancel appointments in your database.

Your manual steps:

1. Open **http://127.0.0.1:8000/?phase=3**, or refresh your existing tab. Click **Start a call** and allow microphone access.
2. Watch **Calling clinic** change to **Connected**. The timer starts when the assistant is ready. Speak and check the waveform, transcript, and spoken reply.
3. Try **Mute**, **Unmute**, and **Mic input**. Mic input opens the device selector and input meter; choose your laptop microphone if necessary. The speaker icon at the top toggles only the ring/hang-up sounds, not Aster's voice.
4. Book a future slot using a fictional phone number and confirm the full spoken readback. Check the green confirmation card for the correct doctor, date, and time.
5. End the call, then click **Back to dashboard**. The changed appointment is brought into view and highlighted; its doctor's availability updates automatically.
6. Make another call and cancel the test appointment with the same number. Confirm the fresh readback, check the cancellation card, then check the highlighted cancelled row and restored slot.
7. Test a phone-number correction before confirming. No appointment should change until the correct number is fully read back and confirmed. This and spoken cancellation remain required manual checks for Phase 2.
8. Try a narrow browser window, end the call, and use **Call again**. The timer, transcript, and confirmation card should reset. Verify the ringing and end sounds are comfortable on your speakers or headphones.

No new account, API key, or installation is needed for this frontend update. Your listening test confirms physical microphone behavior and audio quality.

## Phase 4 — manually finish the submission

1. Create a GitHub repository in your account. Push the complete source after we finish the final checks. Include README, `.env.example`, dependency files, and both frontend/voice code. Exclude `.env`, keys, `.venv`, local database, and recordings with private information.
2. Rehearse: start call → say fictional phone number → agent reads it back → confirm → ask for doctor availability → pick a slot → book → show the dashboard update.
3. Record up to **three minutes** of the running application and audible conversation. Check the recording includes microphone and assistant audio.
4. Write or adapt a short, honest pipeline description in your own words. Explain what each service does and how the three tools access SQLite. Do not claim any unfinished feature.
5. Verify the repository and recording links are accessible to the reviewer.
6. Submit the GitHub link, video, and pipeline description through the [Google Form specified in the assignment](https://docs.google.com/forms/d/e/1FAIpQLSdruhcgKFC4LjnlwHfYDRZoGsa0r-qy4k68SJ8RsmxsPbYxpg/viewform?usp=publish-editor). The PDF says **Wednesday, 25 November, 11:00 PM IST** and asks applicants not to submit by replying to the email.

Deployment is not listed as required. We will prioritize the working local voice flow and recording before considering hosting.
