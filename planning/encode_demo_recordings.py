"""Encode actual browser screenshots sampled during live app interactions."""
import json
from pathlib import Path
import subprocess
import sys
import hashlib

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'.local/media-deps'))
import imageio_ffmpeg
FFMPEG=imageio_ffmpeg.get_ffmpeg_exe()
FRAMES=ROOT/'.local/recording-frames';OUT=ROOT/'demos';OUT.mkdir(exist_ok=True)
SEGMENTS=[
 ('patient-history-directory','Patient history source provenance and separate physician checks'),
 ('patient-booking','Booking alone creates no record permission'),
 ('physician-booking-no-consent','Physician has no reports before explicit permission'),
 ('patient-explicit-sharing','Patient explicitly shares only R01 version 1 for a bounded interval'),
 ('physician-authorized-version','Physician reads the authorized version and source evidence'),
 ('physician-current-state-block','Separate controlled registration invalidation blocks a new request in the same session'),
 ('lab-held-submission','A specimen mismatch remains held and unpublished'),
 ('lab-amendment-submission','Lab proposes version 2 with a reason and distinct approver'),
 ('lab-distinct-approval','Distinct source approval publishes version 2 and preserves version 1'),
 ('hospital-profile-separation','Hospital profile and registration review request confer no clinical privilege'),
 ('hospital-affiliation-change','Separate affiliation revocation and renewal leave registration unchanged'),
 ('physician-correction-scope','Existing version 1 permission exposes only the historical version'),
 ('patient-corrected-history-withdrawal','Patient sees correction lineage and withdraws old permission')]
outputs=[]
for name,title in SEGMENTS:
    folder=FRAMES/name;meta=json.loads((folder/'frames.json').read_text());frames=meta['frames']
    require_duration=min(meta['duration_ms']/1000,10.0)
    # Trim only the trailing wait in a recorded explicit-share segment. The
    # save is visible before this point; no UI outcome is synthesized.
    if name=='patient-explicit-sharing':require_duration=min(require_duration,7.5)
    entries=[]
    for i,f in enumerate(frames):
        start=f['time_ms']/1000
        if start>=require_duration:break
        end=min(frames[i+1]['time_ms']/1000 if i+1<len(frames) else require_duration,require_duration)
        entries+=['file '+"'"+(folder/f['file']).as_posix()+"'",'duration %.6f'%max(.02,end-start)]
    entries+=['file '+"'"+(folder/frames[min(i,len(frames)-1)]['file']).as_posix()+"'"]
    listing=folder/'concat.txt';listing.write_text('\n'.join(entries),encoding='utf-8')
    dest=FRAMES/(name+'.mp4')
    command=[FFMPEG,'-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(listing),
             '-vf','scale=1280:800:force_original_aspect_ratio=decrease,pad=1280:800:(ow-iw)/2:(oh-ih)/2,fps=12,format=yuv420p',
             '-c:v','libx264','-crf','20','-preset','fast','-movflags','+faststart',str(dest)]
    subprocess.run(command,check=True)
    outputs.append({'segment':name,'title':title,'seconds':require_duration,'captured_frames':len(frames),'source':'Actual working app browser screenshots at approximately four samples per second; role sign-ins omitted.'})

groups={
 'patient-sharing.mp4':['patient-history-directory','patient-booking','patient-explicit-sharing','patient-corrected-history-withdrawal'],
 'physician-access.mp4':['physician-booking-no-consent','physician-authorized-version','physician-current-state-block','physician-correction-scope'],
 'laboratory-provenance.mp4':['lab-held-submission','lab-amendment-submission','lab-distinct-approval'],
 'hospital-affiliation.mp4':['hospital-profile-separation','hospital-affiliation-change'],
 'sehataman-complete-walkthrough.mp4':[s[0] for s in SEGMENTS]}
manifest=[]
for filename,names in groups.items():
    listing=FRAMES/(filename+'.txt');listing.write_text('\n'.join("file '"+(FRAMES/(n+'.mp4')).as_posix()+"'" for n in names),encoding='utf-8')
    dest=OUT/filename
    subprocess.run([FFMPEG,'-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(listing),'-c','copy','-movflags','+faststart',str(dest)],check=True)
    # Decode the entire finished video, detecting invalid/truncated media.
    subprocess.run([FFMPEG,'-hide_banner','-loglevel','error','-i',str(dest),'-f','null','-'],check=True)
    manifest.append({'file':filename,'bytes':dest.stat().st_size,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'segments':names,'full_decode_check':'passed'})
(OUT/'recording_manifest.json').write_text(json.dumps({'all_synthetic':True,'format':'MP4 H264 1280x800 12fps output; actual browser sampling approximately 4fps','audio':'none','editing':'Live captured segments concatenated; authentication and waiting intervals omitted. No generated app footage.','segments':outputs,'files':manifest},indent=2),encoding='utf-8')
print(json.dumps(manifest,indent=2))
