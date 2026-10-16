// The four remade video ads. Copy and product facts follow ads/ads.json and the Meta ads playbook:
// 16 paths, 756 video lessons, an AI mentor, Start free. No income promises, no OnlyFans chapter.
import React from 'react';
import {AbsoluteFill, Audio, Series, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {Beat, Bg, C, Caption, EndCard, LAYOUT, Phone, Words, bedVolume} from './kit';

const S = (sec) => Math.round(sec * 30);
const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'};

// ---------- ad01: "I watched 47 videos" ----------
const HYPE = ['MAKE MONEY ONLINE', '10 SIDE HUSTLES', 'QUIT YOUR 9-5?', 'PASSIVE INCOME', 'NOBODY TELLS YOU THIS', 'DO THIS NOW',
  'BEGINNER MISTAKES', 'WATCH TILL THE END', 'THE SECRET METHOD', 'START TODAY', 'I TRIED IT FOR 30 DAYS', 'STOP DOING THIS'];
const TILE = ['#3B2A1E', '#1E2D3B', '#3B1E2A', '#2A3B1E', '#2D1E3B', '#3B361E'];

const ThumbWall = ({fmt}) => {
  const frame = useCurrentFrame();
  const L = LAYOUT[fmt];
  const cols = 3, tw = 400, th = 225, gap = 22;
  return (
    <AbsoluteFill style={{overflow: 'hidden', rotate: '-8deg', scale: '1.25'}}>
      {Array.from({length: cols}).map((_, c) => (
        <div key={c} style={{position: 'absolute', left: c * (tw + gap) - 90, top: -400 + (c % 2 ? -1 : 1) * frame * 3.2 - (c % 2 ? 0 : 300),
          display: 'flex', flexDirection: 'column', gap}}>
          {Array.from({length: 12}).map((_, r) => {
            const i = (r * 5 + c * 7) % HYPE.length;
            return (
              <div key={r} style={{width: tw, height: th, borderRadius: 18, background: TILE[(r + c) % TILE.length], position: 'relative',
                padding: 22, display: 'flex', alignItems: 'flex-end', fontWeight: 800, fontSize: 38, lineHeight: 1.05, color: '#fff'}}>
                {HYPE[i]}
                <span style={{position: 'absolute', right: 14, bottom: 14, background: 'rgba(0,0,0,.75)', fontSize: 22, fontWeight: 600,
                  padding: '3px 8px', borderRadius: 6}}>{`${8 + ((r * 3 + c) % 14)}:${String((r * 17 + c * 11) % 60).padStart(2, '0')}`}</span>
              </div>
            );
          })}
        </div>
      ))}
      <AbsoluteFill style={{background: 'rgba(12,19,16,.72)'}} />
      <div style={{position: 'absolute', inset: 0, height: L.h}} />
    </AbsoluteFill>
  );
};

const Count47 = ({fmt}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const n = Math.round(interpolate(frame, [4, 34], [1, 47], {...clamp, easing: (t) => 1 - Math.pow(1 - t, 3)}));
  const pop = spring({frame: frame - 34, fps, config: {damping: 9, stiffness: 260}});
  const L = LAYOUT[fmt];
  return (
    <Beat fmt={fmt}>
      <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6}}>
        <Words text="I watched" size={L.capSize} />
        <div style={{fontSize: L.big * 2.1, fontWeight: 800, color: C.gold, letterSpacing: '-0.05em', lineHeight: 1,
          scale: String(1 + 0.08 * pop * (1 - pop))}}>{n}</div>
        <Words text="“make money online” videos" delay={8} size={L.capSize} />
      </div>
    </Beat>
  );
};

export const Ad01 = ({fmt}) => {
  const total = S(19.8);
  const lessonAt = S(2.4 + 2 + 3 + 3);
  return (
    <Bg>
      <Audio src={staticFile('bed.mp3')} volume={bedVolume(30, total, [[lessonAt, lessonAt + S(3.6)]])} />
      <Series>
        <Series.Sequence durationInFrames={S(2.4)}><ThumbWall fmt={fmt} /><Count47 fmt={fmt} /></Series.Sequence>
        <Series.Sequence durationInFrames={S(2)}>
          <Beat fmt={fmt}><Words text="…and still didn’t know what to do on *Monday.*" size={LAYOUT[fmt].capSize + 6} /></Beat>
        </Series.Sequence>
        <Series.Sequence durationInFrames={S(3)}>
          <Caption fmt={fmt} text="So we built the *actual steps.*" />
          <Phone fmt={fmt} src="home" from={1.9} zoom={[1, 1.04]} />
        </Series.Sequence>
        <Series.Sequence durationInFrames={S(3)}>
          <Caption fmt={fmt} text="*16* real paths. Every step *in order.*" />
          <Phone fmt={fmt} src="course" from={0} zoom={[1.02, 1.08]} enter={false} />
        </Series.Sequence>
        <Series.Sequence durationInFrames={S(3.6)}>
          <Caption fmt={fmt} text="*756* short lessons. Each one has a *video.*" />
          <Phone fmt={fmt} src="lesson" from={0.2} volume={1} enter={false} />
        </Series.Sequence>
        <Series.Sequence durationInFrames={S(2.6)}>
          <Caption fmt={fmt} text="An _AI mentor_ when you’re stuck." />
          <Phone fmt={fmt} src="mentor" from={3.8} zoom={[1.0, 1.06]} focus="50% 45%" enter={false} />
        </Series.Sequence>
        <Series.Sequence durationInFrames={S(3.2)}>
          <EndCard fmt={fmt} headline="Stop watching. *Start building.*" />
        </Series.Sequence>
      </Series>
    </Bg>
  );
};
export const AD01_SECONDS = 19.8;

// ---------- ad02: "The AI mentor wrote my DM" ----------
export const Ad02 = ({fmt}) => {
  const total = S(15.8);
  return (
    <Bg>
      <Audio src={staticFile('bed.mp3')} volume={bedVolume(30, total)} />
      <Series>
        <Series.Sequence durationInFrames={S(2.2)}>
          <Beat fmt={fmt}><Words text="I asked an _AI business mentor_ how to land my *first client.*" size={LAYOUT[fmt].capSize + 6} stagger={2} /></Beat>
        </Series.Sequence>
        <Series.Sequence durationInFrames={S(4.8)}>
          <Caption fmt={fmt} text="Here’s what it *said.*" delay={10} />
          <Phone fmt={fmt} src="mentor" from={2.7} zoom={[1, 1.05]} focus="50% 55%" />
        </Series.Sequence>
        <Series.Sequence durationInFrames={S(4.2)}>
          <Caption fmt={fmt} text="Then it wrote the *message* for me." />
          <Phone fmt={fmt} src="mentor" from={7.5} zoom={[1.04, 1.12]} focus="50% 62%" enter={false} />
        </Series.Sequence>
        <Series.Sequence durationInFrames={S(1.4)}>
          <Beat fmt={fmt}><Words text="Copy. Paste. *Send.*" size={LAYOUT[fmt].big * 0.8} stagger={6} /></Beat>
        </Series.Sequence>
        <Series.Sequence durationInFrames={S(3.2)}>
          <EndCard fmt={fmt} headline="Your _AI business mentor._" sub="Built into every path. Module 1 of every course is free." />
        </Series.Sequence>
      </Series>
    </Bg>
  );
};
export const AD02_SECONDS = 15.8;

// ---------- ad03: "Stop scrolling" ----------
const Strike = ({name, price, at}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = spring({frame: frame - at, fps, config: {damping: 16, stiffness: 180}});
  const line = interpolate(frame, [at + 10, at + 18], [0, 1], clamp);
  return (
    <div style={{position: 'relative', width: '100%', maxWidth: 760, display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      background: C.card, border: `2px solid ${C.line2}`, borderRadius: 24, padding: '30px 38px', opacity: p, translate: `${(1 - p) * 80}px 0`}}>
      <div>
        <div style={{fontSize: 24, fontWeight: 700, color: C.soft, letterSpacing: '.12em'}}>ONLINE COURSE</div>
        <div style={{fontSize: 46, fontWeight: 800}}>{name}</div>
      </div>
      <div style={{fontSize: 54, fontWeight: 800, color: C.gold}}>{price}</div>
      <div style={{position: 'absolute', left: 20, right: 20, top: '50%', height: 8, borderRadius: 8, background: C.red,
        scale: `${line} 1`, transformOrigin: 'left center', rotate: '-4deg'}} />
    </div>
  );
};

const Stop = ({fmt}) => {
  const frame = useCurrentFrame();
  const L = LAYOUT[fmt];
  const shake = frame < 12 ? Math.sin(frame * 2.4) * (12 - frame) * 0.5 : 0;
  return (
    <Beat fmt={fmt}>
      <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center'}}>
        <div style={{fontSize: L.big * 1.7, fontWeight: 800, color: C.red, letterSpacing: '-0.05em', lineHeight: 1, rotate: `${shake}deg`}}>STOP</div>
        <Words text="scrolling." delay={4} size={L.capSize + 10} />
      </div>
    </Beat>
  );
};

export const Ad03 = ({fmt}) => {
  const total = S(18.3);
  const feed = fmt === 'feed';
  return (
    <Bg>
      <Audio src={staticFile('bed.mp3')} volume={bedVolume(30, total)} />
      <Series>
        <Series.Sequence durationInFrames={S(1.6)}><Stop fmt={fmt} /></Series.Sequence>
        <Series.Sequence durationInFrames={S(2.2)}>
          <Beat fmt={fmt}>
            <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: feed ? 22 : 34, width: '100%'}}>
              <Words text="You don’t need *another course.*" size={LAYOUT[fmt].capSize} />
              <div style={{height: feed ? 6 : 20}} />
              <Strike name="Dropship Mastery" price="$997" at={8} />
              <Strike name="Agency Accelerator" price="$1,497" at={14} />
              <Strike name="Creator Pro" price="$1,997" at={20} />
            </div>
          </Beat>
        </Series.Sequence>
        <Series.Sequence durationInFrames={S(1.5)}>
          <Beat fmt={fmt}><Words text="You need a *plan.*" size={LAYOUT[fmt].big} stagger={4} /></Beat>
        </Series.Sequence>
        <Series.Sequence durationInFrames={S(2.4)}>
          <Caption fmt={fmt} kicker="1" text="Pick a path." />
          <Phone fmt={fmt} src="home" from={3.0} />
        </Series.Sequence>
        <Series.Sequence durationInFrames={S(2.6)}>
          <Caption fmt={fmt} kicker="2" text="Follow the steps." />
          <Phone fmt={fmt} src="course" from={4.3} enter={false} />
        </Series.Sequence>
        <Series.Sequence durationInFrames={S(2.6)}>
          <Caption fmt={fmt} kicker="3" text="Ask when you’re *stuck.*" />
          <Phone fmt={fmt} src="mentor" from={3.0} zoom={[1, 1.05]} focus="50% 50%" enter={false} />
        </Series.Sequence>
        <Series.Sequence durationInFrames={S(2.2)}>
          <Caption fmt={fmt} kicker="4" text="Show up *every day.*" />
          <Phone fmt={fmt} src="home" from={0} rate={0.4} zoom={[1.45, 1.55]} focus="6% 70%" enter={false} />
        </Series.Sequence>
        <Series.Sequence durationInFrames={S(3.2)}>
          <EndCard fmt={fmt} headline="Pick a path. *Follow the steps.*" />
        </Series.Sequence>
      </Series>
    </Bg>
  );
};
export const AD03_SECONDS = 18.3;

// ---------- ad04: "A $997 course vs The Guide" ----------
const ROWS = [
  ['PRICE', '$997+ upfront', 'Under $1/day*'],
  ['WHAT YOU GET', 'Hours of hype videos', '756 video lessons'],
  ['WHEN YOU’RE STUCK', 'Pay extra for “the Discord”', 'AI mentor, any time'],
  ['TOOLS', 'Buy them separately', 'Templates + tools included'],
  ['BUSINESS PATHS', 'Usually just one', '16 to choose from'],
];

const Mark = ({ok, size}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={ok ? C.green : C.red} strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" style={{flex: 'none'}}>
    {ok ? <path d="M20 6 9 17l-5-5" /> : <path d="M18 6 6 18M6 6l12 12" />}
  </svg>
);

const Versus = ({fmt}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const feed = fmt === 'feed';
  const k = feed ? 0.8 : 1.16;
  const head = spring({frame, fps, config: {damping: 14, stiffness: 180}});
  const rowAt = (i) => 22 + i * 30;
  const dim = interpolate(frame, [rowAt(5) + 6, rowAt(5) + 16], [1, 0.38], clamp);
  const cell = (ok) => ({flex: 1, display: 'flex', alignItems: 'center', gap: 14 * k, padding: `${22 * k}px ${24 * k}px`, borderRadius: 20 * k,
    fontSize: 36 * k, fontWeight: 700, lineHeight: 1.15, background: ok ? 'rgba(63,203,147,.12)' : C.card,
    border: `2px solid ${ok ? C.green : C.line2}`, color: ok ? C.ink : C.ink2, opacity: ok ? 1 : dim});
  return (
    <AbsoluteFill style={{padding: feed ? '0 60px' : '0 56px 140px', gap: 18 * k, justifyContent: 'center'}}>
      <div style={{display: 'flex', gap: 18 * k, alignItems: 'stretch', scale: String(0.8 + 0.2 * head), opacity: head}}>
        <div style={{...cell(false), justifyContent: 'center', flexDirection: 'column', alignItems: 'flex-start', gap: 4, opacity: dim}}>
          <span style={{fontSize: 24 * k, letterSpacing: '.12em', color: C.soft}}>A TYPICAL</span>
          <span style={{fontSize: 46 * k, fontWeight: 800, color: C.ink}}>$997 course</span>
        </div>
        <div style={{...cell(true), justifyContent: 'center', flexDirection: 'column', alignItems: 'flex-start', gap: 4}}>
          <span style={{fontSize: 24 * k, letterSpacing: '.12em', color: C.green}}>THE GUIDE</span>
          <span style={{fontSize: 46 * k, fontWeight: 800}}>Free to start</span>
        </div>
      </div>
      {ROWS.map(([label, bad, good], i) => {
        const p = spring({frame: frame - rowAt(i), fps, config: {damping: 16, stiffness: 190}});
        return (
          <div key={label} style={{opacity: p, translate: `0 ${(1 - p) * 40}px`}}>
            <div style={{textAlign: 'center', fontSize: 22 * k, fontWeight: 700, letterSpacing: '.14em', color: C.soft, margin: `${12 * k}px 0 ${10 * k}px`}}>{label}</div>
            <div style={{display: 'flex', gap: 18 * k}}>
              <div style={cell(false)}><Mark ok={false} size={34 * k} />{bad}</div>
              <div style={cell(true)}><Mark ok size={34 * k} />{good}</div>
            </div>
          </div>
        );
      })}
      <div style={{textAlign: 'center', fontSize: 24 * k, color: C.soft, marginTop: 10 * k, opacity: interpolate(frame, [rowAt(1), rowAt(1) + 10], [0, 1], clamp)}}>
        *Pro yearly plan, $149 a year
      </div>
    </AbsoluteFill>
  );
};

export const Ad04 = ({fmt}) => {
  const total = S(15.4);
  return (
    <Bg>
      <Audio src={staticFile('bed.mp3')} volume={bedVolume(30, total)} />
      <Series>
        <Series.Sequence durationInFrames={S(7.6)}><Versus fmt={fmt} /></Series.Sequence>
        <Series.Sequence durationInFrames={S(1.5)}>
          <Caption fmt={fmt} text="See it for *yourself.*" />
          <Phone fmt={fmt} src="lesson" from={1.0} />
        </Series.Sequence>
        <Series.Sequence durationInFrames={S(1.5)}>
          <Caption fmt={fmt} text="Contracts. Emails. *Templates.*" delay={0} />
          <Phone fmt={fmt} src="templates" from={0.4} enter={false} />
        </Series.Sequence>
        <Series.Sequence durationInFrames={S(1.6)}>
          <Caption fmt={fmt} text="And a _mentor_ for the hard parts." delay={0} />
          <Phone fmt={fmt} src="mentor" from={4.2} focus="50% 45%" zoom={[1.02, 1.06]} enter={false} />
        </Series.Sequence>
        <Series.Sequence durationInFrames={S(3.2)}>
          <EndCard fmt={fmt} headline="Easy *choice.*" sub="Pro from $24.99/mo. Module 1 of every course is free." />
        </Series.Sequence>
      </Series>
    </Bg>
  );
};
export const AD04_SECONDS = 15.4;
