# --- SYSTEM CHECK START ---
print("--- RECAP MAKER SYSTEM STARTING ---")
try:
    import flask
    from flask import Flask, render_template, request, jsonify, session, send_file, after_this_request
    import yt_dlp
    import ffmpeg
    import edge_tts
    import speech_recognition
    import groq
    import queue
    print("✅ All Libraries Loaded Successfully!")
except ImportError as e:
    print(f"❌ CRITICAL ERROR: Missing Library -> {e}")
    exit()
# --- SYSTEM CHECK END ---

import os
import uuid
import logging
import threading
import time
from werkzeug.utils import secure_filename
from utils import process_video_edit, create_ai_audio, analyze_script_with_ai

# Disable heavy logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# --- 1. TEMPLATE FOLDER CHANGE ---
app = Flask(__name__, template_folder='.')
# Session key keeps purely for UI purposes, not for file security anymore
app.secret_key = os.environ.get('SECRET_KEY', 'secure-recap-maker-key')

# --- CONFIG ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static/uploads')
PROCESSED_FOLDER = os.path.join(BASE_DIR, 'static/processed')

for f in [UPLOAD_FOLDER, PROCESSED_FOLDER]:
    os.makedirs(f, exist_ok=True)

# --- QUEUE SYSTEM ---
task_queue = queue.Queue()
jobs = {} 

# --- WORKER 1: VIDEO PROCESSING ---
def worker():
    print("👷 Video Processing Worker Started...")
    while True:
        try:
            job_id, input_p, output_p, opts = task_queue.get()
            print(f"⚙️ Worker: Starting Job {job_id}")
            jobs[job_id]['status'] = 'processing'
            
            success, err_msg = process_video_edit(input_p, output_p, opts)
            
            if success:
                filename = os.path.basename(output_p)
                download_url = f"/stream-and-delete/{filename}"
                jobs[job_id] = {'status': 'success', 'url': download_url}
                print(f"✅ Job {job_id} Complete!")
            else:
                jobs[job_id] = {'status': 'failed', 'message': f'Rendering Failed: {err_msg}'}
                print(f"❌ Job {job_id} Failed! Reason: {err_msg}")

            task_queue.task_done()
        except Exception as e:
            print(f"Worker Crash: {e}")
            if 'job_id' in locals():
                jobs[job_id] = {'status': 'failed', 'message': str(e)}

# --- WORKER 2: AUTO CLEANUP ---
def cleanup_worker():
    print("🧹 Auto Cleanup Worker Started...")
    while True:
        try:
            time.sleep(600)
            now = time.time()
            cutoff = 1800 
            
            folders = [UPLOAD_FOLDER, PROCESSED_FOLDER]
            deleted_count = 0
            
            for folder in folders:
                if not os.path.exists(folder): continue
                for filename in os.listdir(folder):
                    file_path = os.path.join(folder, filename)
                    if not os.path.isfile(file_path) or filename.startswith('.'): continue
                    
                    try:
                        file_age = now - os.path.getmtime(file_path)
                        if file_age > cutoff:
                            os.remove(file_path)
                            deleted_count += 1
                    except Exception as e:
                        print(f"⚠️ Cleanup Access Error: {filename} - {e}")
            
            if deleted_count > 0:
                print(f"🗑️ Cleaned up {deleted_count} old files.")
        except Exception as e:
            print(f"Cleanup Loop Error: {e}")

threading.Thread(target=worker, daemon=True).start()
threading.Thread(target=cleanup_worker, daemon=True).start()

# --- HELPER: GET USER ID (UI Display Only) ---
def get_user_id():
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())[:6] 
    return session['user_id']

# --- ROUTES ---

@app.route('/')
def home():
    uid = get_user_id()
    return render_template('index.html', user_id=uid)

@app.route('/stream-and-delete/<filename>')
def stream_and_delete(filename):
    try:
        path = os.path.join(PROCESSED_FOLDER, filename)
        if not os.path.exists(path):
            return jsonify({'status': 'error', 'message': 'File not found or expired'}), 404

        @after_this_request
        def remove_file(response):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception as e:
                print(f"⚠️ Error deleting {filename}: {e}")
            return response

        return send_file(path, as_attachment=False)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/upload-video', methods=['POST'])
def up_video():
    try:
        if 'video_file' not in request.files:
            return jsonify({'status':'error', 'message': 'No file part'})
            
        f = request.files['video_file']
        if f.filename == '':
            return jsonify({'status':'error', 'message': 'No selected file'})
        
        ext = f.filename.rsplit('.', 1)[1].lower() if '.' in f.filename else 'mp4'
        
        # --- SECURITY FIX: ULTRA-SECURE FILENAME ---
        # We use a 32-character UUID Hex.
        # Probability of collision is virtually zero.
        # Example: vid_a1b2c3d4e5f678901234567890abcdef.mp4
        secure_uuid = uuid.uuid4().hex
        safe_name = f"vid_{secure_uuid}.{ext}"
        
        path = os.path.join(UPLOAD_FOLDER, safe_name)
        f.save(path)
        
        return jsonify({
            'status':'success', 
            'filename':safe_name, 
            'path':f'/static/uploads/{safe_name}', 
            'translated_text': ''
        })
    except Exception as e: 
        print(f"Upload Error: {e}")
        return jsonify({'status':'error', 'message':str(e)})

@app.route('/download-video', methods=['POST'])
def dl_video():
    try:
        url = request.json.get('url')
        if not url: return jsonify({'status':'error', 'message': 'No URL'})
        
        # --- SECURITY FIX ---
        secure_uuid = uuid.uuid4().hex
        
        opts = {
            'outtmpl': os.path.join(UPLOAD_FOLDER, f'vid_{secure_uuid}.%(ext)s'),
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'noplaylist': True, 
            'quiet': True,
            'nocheckcertificate': True,
        }
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
            
        # Find the file we just downloaded (starts with vid_secure_uuid)
        target_prefix = f"vid_{secure_uuid}"
        f = next((x for x in os.listdir(UPLOAD_FOLDER) if x.startswith(target_prefix)), None)
        
        if f:
            path = os.path.join(UPLOAD_FOLDER, f)
            txt = analyze_script_with_ai(path)
            return jsonify({'status':'success', 'filename':f, 'path':f'/static/uploads/{f}', 'translated_text':txt})
        return jsonify({'status':'error', 'message': 'Download failed'})
    except Exception as e: return jsonify({'status':'error', 'message':str(e)})

@app.route('/re-analyze', methods=['POST'])
def re_analyze():
    try:
        filename = request.form.get('filename')
        
        if not filename: return jsonify({'status':'error', 'message':'No file specified'})
        
        # Since filenames are random 32-char UUIDs, 
        # knowing the filename IS the authorization.
        path = os.path.join(UPLOAD_FOLDER, filename)
        
        if not os.path.exists(path): 
            return jsonify({'status':'error', 'message':'File not found (Expired)'})

        txt = analyze_script_with_ai(path)
        return jsonify({'status':'success', 'translated_text': txt})
    except Exception as e: return jsonify({'status':'error', 'message':str(e)})

@app.route('/process', methods=['POST'])
def start_process():
    try:
        d = request.form
        vname = d.get('video_filename')
        
        if not vname:
             return jsonify({'status':'error', 'message':'No video selected'})
        
        ip = os.path.join(UPLOAD_FOLDER, vname)
        if not os.path.exists(ip): 
            return jsonify({'status':'error', 'message':'Source video not found (Expired)'})

        # Generate unique output filename
        job_id = uuid.uuid4().hex
        op = os.path.join(PROCESSED_FOLDER, f"recap_{job_id}.mp4")
        
        def is_on(k): return d.get(k) in ['on', 'true', '1']
        
        opts = {
            'text_watermark': d.get('text_watermark'),
            'blur_enabled': is_on('blur_enabled'),
            'blur_x': int(float(d.get('blur_x',0))), 'blur_y': int(float(d.get('blur_y',0))),
            'blur_w': int(float(d.get('blur_w',0))), 'blur_h': int(float(d.get('blur_h',0))),
            'logo_x': int(float(d.get('logo_x',1))), 'logo_y': int(float(d.get('logo_y',1))),
            'logo_w': int(float(d.get('logo_w',100))), 'logo_h': int(float(d.get('logo_h',100))),
            'bypass_flip': is_on('bypass_flip'), 
            'bypass_zoom': is_on('bypass_zoom'),
            'bypass_speed': is_on('bypass_speed'), 
            'bypass_color': is_on('bypass_color'),
            'monezlation': is_on('monezlation'),
        }

        if request.files.get('logo_file'):
            l = request.files['logo_file']
            if l.filename:
                # Use secure UUID for logo too
                lp = os.path.join(UPLOAD_FOLDER, f"logo_{job_id}.png")
                l.save(lp)
                opts['logo_path'] = lp
        
        if d.get('ai_text'):
            ap = os.path.join(UPLOAD_FOLDER, f"audio_{job_id}.mp3")
            gender = d.get('voice_gender','male')
            if create_ai_audio(d.get('ai_text'), ap, gender):
                opts['ai_audio_path'] = ap
        
        jobs[job_id] = {'status': 'queued'}
        task_queue.put((job_id, ip, op, opts))
        
        return jsonify({'status':'queued', 'job_id': job_id, 'message': 'Added to Queue'})
        
    except Exception as e: return jsonify({'status':'error', 'message':str(e)})

@app.route('/status/<job_id>')
def check_status(job_id):
    job = jobs.get(job_id)
    if not job: return jsonify({'status': 'not_found'})
    return jsonify(job)

if __name__ == '__main__':
    print("🚀 Recap Maker Server Running on Port 7860...")
    app.run(debug=False, port=7860, host='0.0.0.0')
    