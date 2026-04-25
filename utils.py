import ffmpeg
import os
import asyncio
import edge_tts
import uuid
import time
import math  # <--- Added for smart loop calculation
from google import genai
from google.genai import types
from groq import Groq

# --- 1. GEMINI MANAGER (DYNAMIC FETCH & FLASH ONLY) ---
class GeminiManager:
    def __init__(self):
        self.keys = []
        for i in range(1, 6):
            k = os.getenv(f'GEMINI_API_KEY_{i}')
            if k: self.keys.append(k)
        
        if not self.keys:
            k = os.getenv('GEMINI_API_KEY')
            if k: self.keys.append(k)

        self.key_models_cache = {}
        self.key_status = {}
        for k in self.keys:
            self.key_status[k] = {"usage_count": 0, "window_start": time.time(), "cooldown_until": 0}
        self.RPM_LIMIT = 12

    def get_healthy_key(self):
        current_time = time.time()
        for key in self.keys:
            stats = self.key_status[key]
            if current_time < stats["cooldown_until"]: continue
            if current_time - stats["window_start"] > 60:
                stats["usage_count"] = 0; stats["window_start"] = current_time
            if stats["usage_count"] < self.RPM_LIMIT:
                stats["usage_count"] += 1
                return key
        time.sleep(1)
        return self.get_healthy_key()

    def mark_key_error(self, key):
        print(f"⚠️ Key Error on ...{key[-4:]}. Cooling down.")
        self.key_status[key]["cooldown_until"] = time.time() + 60

    def fetch_flash_models(self, client, key):
        if key in self.key_models_cache: return self.key_models_cache[key]
        try:
            flash_list = []
            for m in client.models.list():
                if 'flash' in m.name.lower():
                    flash_list.append(m.name.replace('models/', ''))
            flash_list.sort(reverse=True)
            if not flash_list: flash_list = ["gemini-1.5-flash"]
            self.key_models_cache[key] = flash_list
            return flash_list
        except: return ["gemini-1.5-flash"]

    def translate_text(self, text):
        max_attempts = 3
        attempts = 0
        last_error = ""
        
        while attempts < max_attempts:
            key = self.get_healthy_key()
            if not key: return "System Busy"
            
            try:
                client = genai.Client(api_key=key, http_options={'api_version': 'v1beta'})
                available_models = self.fetch_flash_models(client, key)
                
                for model_name in available_models:
                    try:
                        response = client.models.generate_content(
                            model=model_name,
                            contents=text,
                            config=types.GenerateContentConfig(
                                temperature=0.3,
                                max_output_tokens=8192,
                                system_instruction=(
                                    "You are a Translator. Convert the input English text into 'Natural Spoken Burmese' (အပြောစကား). "
                                    "Output ONLY the Burmese translation. No Markdown."
                                )
                            )
                        )
                        return response.text.strip()
                    except Exception as e:
                        err = str(e).lower()
                        if "429" in err or "403" in err or "resource exhausted" in err:
                            self.mark_key_error(key)
                            break 
                        continue 
            except Exception as e:
                last_error = str(e)
            attempts += 1
        return f"Translation Failed: {last_error}"

gemini_manager = GeminiManager()

# --- 2. GROQ LOGIC ---
def transcribe_audio_groq(audio_path):
    try:
        k = os.getenv('GROQ_API_KEY_1') or os.getenv('GROQ_API_KEY')
        if not k: return None
        client = Groq(api_key=k)
        with open(audio_path, "rb") as file:
            transcription = client.audio.transcriptions.create(
                file=(os.path.basename(audio_path), file.read()),
                model="whisper-large-v3-turbo", 
                response_format="text"
            )
        return str(transcription).strip()
    except Exception as e:
        print(f"❌ Groq Transcription Error: {e}")
        return None

# --- 3. MAIN ANALYSIS ---
def analyze_script_with_ai(video_path):
    unique_id = str(uuid.uuid4())[:8]
    audio_path = f"temp_{unique_id}.mp3"
    try:
        if os.path.exists(audio_path): os.remove(audio_path)
        (
            ffmpeg.input(video_path)
            .output(audio_path, format='mp3', acodec='libmp3lame', ab='64k') 
            .run(quiet=True, overwrite_output=True)
        )
        print("🚀 Step 1: Transcribing with Groq...")
        english_text = transcribe_audio_groq(audio_path)
        if not english_text:
            if os.path.exists(audio_path): os.remove(audio_path)
            return "Transcription Failed (Check Groq Key)"
            
        print(f"🧠 Step 2: Translating {len(english_text)} chars with Gemini...")
        burmese_text = gemini_manager.translate_text(english_text)
        
        if os.path.exists(audio_path): os.remove(audio_path)
        return burmese_text
    except Exception as e:
        if os.path.exists(audio_path): os.remove(audio_path)
        return f"Error: {str(e)}"

# --- 4. VIDEO PROCESSING (SMART LOOP FIX) ---
async def generate_voice(text, output_file, voice):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_file)

def create_ai_audio(text, output_path, gender='male'):
    voice = "my-MM-ThihaNeural" if gender == 'male' else "my-MM-NilarNeural"
    try: asyncio.run(generate_voice(text, output_path, voice)); return True
    except: return False

def process_video_edit(input_path, output_path, options):
    try:
        probe = ffmpeg.probe(input_path)
        vid_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        width = int(vid_info['width'])
        height = int(vid_info['height'])
        duration = float(probe['format']['duration'])
        
        input_stream = ffmpeg.input(input_path)
        v = input_stream.video
        a = input_stream.audio

        # --- A. AUDIO SYNC FIRST ---
        if options.get('ai_audio_path') and os.path.exists(options['ai_audio_path']):
            ai_a = ffmpeg.input(options['ai_audio_path']).audio
            ai_probe = ffmpeg.probe(options['ai_audio_path'])
            ai_duration = float(ai_probe['format']['duration'])
            
            if duration > 0 and ai_duration > 0:
                tempo = ai_duration / duration
                if tempo < 0.5: tempo = 0.5
                if tempo > 2.0: tempo = 2.0
                a = ai_a.filter('atempo', tempo).filter('atrim', duration=duration)
            else:
                a = ai_a

        # --- B. SMART MONEZLATION LOOP ---
        if options.get('monezlation') and duration < 70:
            target_duration = 70.0
            # Calculate total plays needed (Ceiling division)
            # E.g., 70 / 20 = 3.5 -> Ceil = 4 total plays
            total_plays = math.ceil(target_duration / duration)
            
            # FFmpeg loop arg is 'repetitions' (plays - 1)
            # If total_plays is 4, we need to repeat 3 times
            loop_count = total_plays - 1
            
            print(f"💰 Loop Calculation: Src={duration}s, Need={target_duration}s -> Plays={total_plays}, FFmpeg_Loop={loop_count}")

            if loop_count > 0:
                v = v.filter('loop', loop=loop_count, size=32767)
                a = a.filter('aloop', loop=loop_count, size=2147483647)
                duration = duration * total_plays

        # Filters
        if options.get('bypass_flip'): v = v.hflip()
        if options.get('bypass_speed'): 
            v = v.filter('setpts', 'PTS/1.05')
            a = a.filter('atempo', '1.05')
        
        if options.get('bypass_zoom'):
            crop_w = int(width * 0.95)
            crop_h = int(height * 0.95)
            v = v.crop(x='(in_w-ow)/2', y='(in_h-oh)/2', width=crop_w, height=crop_h)
            v = v.filter('scale', width, height)

        if options.get('bypass_color'):
            v = v.filter('eq', contrast=1.1, brightness=0.05, saturation=1.2)

        # Coordinate Fix
        if options.get('blur_enabled'):
            bx = int(options.get('blur_x', 0))
            by = int(options.get('blur_y', 0))
            bw = int(options.get('blur_w', 0))
            bh = int(options.get('blur_h', 0))
            if bw > 0 and bh > 0:
                v = v.filter('delogo', x=bx, y=by, w=bw, h=bh)

        if options.get('logo_path'):
            try:
                lw = int(options.get('logo_w', 100))
                lh = int(options.get('logo_h', 100))
                lx = int(options.get('logo_x', 10))
                ly = int(options.get('logo_y', 10))
                logo = ffmpeg.input(options['logo_path']).filter('scale', lw, lh)
                v = v.overlay(logo, x=lx, y=ly)
            except: pass

        try:
            v = v.drawtext(text='Shine Movie Recap', x=50, y=50, fontsize=20, fontcolor='red', box=1, boxcolor='black@0.5')
        except: pass

        output = ffmpeg.output(v, a, output_path, vcodec='libx264', acodec='aac', preset='veryfast', shortest=None)
        output.run(overwrite_output=True, quiet=True)
        return True, "Success"
        
    except Exception as e:
        return False, str(e)
        