#!/usr/bin/env python3
"""Puts finished videos online at a public link so the posting tool (Metricool) can fetch them.

    python3 social/upload.py social/out/video-05efc793.mp4 social/out/photo-06207980.mp4

Videos go on the `social-queue` branch of this (public) GitHub repo. The branch keeps only
today's and yesterday's videos — each run replaces it with a single fresh commit (force push),
so old videos don't pile up in the repository.

Prints JSON: [{"file", "url", "raw_url"}]. `url` is a jsDelivr CDN link pinned to the commit
(served as video/mp4, fast); `raw_url` is the plain GitHub link (fallback — served as a generic
file type, which some tools reject).
"""
import datetime, json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BRANCH = 'social-queue'
RAW = 'https://raw.githubusercontent.com/alexanderlorden433-gif/GUIDE-BACKEND/' + BRANCH + '/'
CDN = 'https://cdn.jsdelivr.net/gh/alexanderlorden433-gif/GUIDE-BACKEND@{sha}/'


def git(*a, cwd=ROOT, check=True):
    return subprocess.run(['git', *a], cwd=cwd, check=check, capture_output=True, text=True)


def main():
    files = [f for f in sys.argv[1:] if f.endswith('.mp4')]
    if not files:
        print(__doc__); sys.exit(1)
    today = datetime.date.today()
    keep_from = (today - datetime.timedelta(days=1)).isoformat()
    tmp = tempfile.mkdtemp(prefix='queue-')
    have_branch = git('fetch', 'origin', f'+refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}', check=False).returncode == 0
    try:
        if have_branch:
            git('worktree', 'add', '--detach', tmp, f'origin/{BRANCH}')
        else:
            git('worktree', 'add', '--detach', tmp, 'HEAD')
        # drop everything except recent videos
        for name in os.listdir(tmp):
            if name == '.git':
                continue
            m = re.match(r'^(\d{4}-\d{2}-\d{2})-', name)
            if not (have_branch and m and m.group(1) >= keep_from and name.endswith('.mp4')):
                p = os.path.join(tmp, name)
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        out = []
        for f in files:
            name = f'{today.isoformat()}-{os.path.basename(f)}'
            shutil.copy(f, os.path.join(tmp, name))
            out.append({'file': f, 'name': name})
        with open(os.path.join(tmp, 'README.md'), 'w') as fh:
            fh.write('# Social video queue\n\nShort-lived copies of The Guide\'s TikTok/Reels videos so the posting tool can fetch them. Replaced every day.\n')
        tmp_branch = 'q-' + datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        git('checkout', '--orphan', tmp_branch, cwd=tmp)
        git('add', '-A', cwd=tmp)
        git('-c', 'user.name=The Guide agents', '-c', 'user.email=noreply@anthropic.com',
            'commit', '-q', '-m', f'Social queue {today.isoformat()}', cwd=tmp)
        r = git('push', '-f', 'origin', f'HEAD:refs/heads/{BRANCH}', cwd=tmp, check=False)
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr); sys.exit(1)
        sha = git('rev-parse', 'HEAD', cwd=tmp).stdout.strip()
        for o in out:
            o['url'] = CDN.format(sha=sha) + o['name']
            o['raw_url'] = RAW + o.pop('name')
        print(json.dumps(out, indent=1))
    finally:
        git('worktree', 'remove', '--force', tmp, check=False)
        git('branch', '-D', tmp_branch, check=False) if 'tmp_branch' in locals() else None
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()
