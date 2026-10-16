// Shared pieces for The Guide's video ads: brand colours, fonts, captions, the phone screen, the end card.
// Everything moves with useCurrentFrame() / spring() so every render is frame-exact.
import React from 'react';
import {
  AbsoluteFill, OffthreadVideo, Easing, continueRender, delayRender, interpolate, spring, staticFile,
  useCurrentFrame, useVideoConfig,
} from 'remotion';

// Forest & Gold, the app's default look (same values as the top of web/index.html).
export const C = {
  bg: '#0C1310', raised: '#101A15', card: '#121C17', card2: '#17241E', line: '#1F2E26', line2: '#2A3D33',
  ink: '#EAF0EC', ink2: '#B7C7BE', soft: '#8CA196', green: '#3FCB93', greenDeep: '#1F9D6B', gold: '#E8B94A',
  onGreen: '#05150D', red: '#F87171',
};
export const FONT = "'Inter', system-ui, sans-serif";

// Inter from public/fonts (copied there by capture.py). The render waits until the fonts are in.
const fontWait = delayRender('Loading Inter');
Promise.all([500, 600, 700, 800].map((w) =>
  new FontFace('Inter', `url(${staticFile(`fonts/inter-${w}.woff2`)}) format('woff2')`, {weight: String(w)})
    .load().then((f) => document.fonts.add(f)),
)).then(() => continueRender(fontWait)).catch((e) => { console.error(e); continueRender(fontWait); });

export const LAYOUT = {
  // story 1080x1920: keep words out of the top 14% and bottom ~20% (Reels/Stories buttons sit there)
  story: {w: 1080, h: 1920, capTop: 300, capH: 330, capSize: 86, phoneW: 860, phoneTop: 660, big: 150},
  // feed 1080x1350
  feed: {w: 1080, h: 1350, capTop: 56, capH: 280, capSize: 64, phoneW: 600, phoneTop: 360, big: 124},
};

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'};

export const Bg = ({children}) => (
  <AbsoluteFill style={{backgroundColor: C.bg, fontFamily: FONT, color: C.ink}}>{children}</AbsoluteFill>
);

export const Logo = ({size = 96, color = C.green}) => (
  <svg width={size} height={size} viewBox="0 0 200 200" aria-hidden="true">
    <circle cx="100" cy="100" r="82" fill="none" stroke={color} strokeWidth="14" />
    <path d="M100,32 L114.1,85.9 L168,100 L114.1,114.1 L100,168 L85.9,114.1 L32,100 L85.9,85.9 Z" fill={color} />
    <circle cx="100" cy="100" r="14" fill={C.gold} />
  </svg>
);

// "Some *gold* words" -> words pop in one after another; *starred* words are gold, _underscored_ words green.
export const Words = ({text, delay = 0, size = 86, align = 'center', stagger = 2, weight = 800, color = C.ink, style}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const words = text.split(' ');
  return (
    <div style={{fontSize: size, fontWeight: weight, lineHeight: 1.08, letterSpacing: '-0.025em', textAlign: align,
      display: 'flex', flexWrap: 'wrap', justifyContent: align === 'center' ? 'center' : 'flex-start', columnGap: size * 0.26, rowGap: size * 0.06, ...style}}>
      {words.map((w, i) => {
        const p = spring({frame: frame - delay - i * stagger, fps, config: {damping: 16, stiffness: 190, mass: 0.7}});
        const gold = /^\*.*\*[.,!?]?$/.test(w); const green = /^_.*_[.,!?]?$/.test(w);
        const clean = w.replace(/^[*_]/, '').replace(/[*_]([.,!?]?)$/, '$1');
        return (
          <span key={i} style={{display: 'inline-block', opacity: p, translate: `0 ${(1 - p) * size * 0.35}px`, scale: String(0.9 + 0.1 * p),
            color: gold ? C.gold : green ? C.green : color}}>{clean}</span>
        );
      })}
    </div>
  );
};

// The caption over a screen clip, in the space above the phone.
export const Caption = ({fmt, text, delay = 3, kicker}) => {
  const L = LAYOUT[fmt];
  return (
    <div style={{position: 'absolute', left: 72, right: 72, top: L.capTop, height: L.capH, display: 'flex', flexDirection: 'column',
      justifyContent: 'flex-end', alignItems: 'center', gap: 18}}>
      {kicker ? <Kicker delay={delay} fmt={fmt}>{kicker}</Kicker> : null}
      <Words text={text} delay={delay + (kicker ? 4 : 0)} size={L.capSize} />
    </div>
  );
};

// a numbered step badge, e.g. "1  Pick a path"
export const Kicker = ({children, delay = 0, fmt}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = spring({frame: frame - delay, fps, config: {damping: 14, stiffness: 200}});
  const s = fmt === 'feed' ? 0.85 : 1;
  return (
    <div style={{width: 84 * s, height: 84 * s, borderRadius: 999, background: C.green, color: C.onGreen, fontWeight: 800,
      fontSize: 50 * s, display: 'flex', alignItems: 'center', justifyContent: 'center', scale: String(p), opacity: p}}>{children}</div>
  );
};

// A real screen recording of the app, in a phone outline that slides up into place.
// zoom: [from, to] over the clip; focus: CSS transform-origin for the zoom.
export const Phone = ({fmt, src, from = 0, rate = 1, zoom = [1, 1], focus = '50% 30%', volume = 0, enter = true, children}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const L = LAYOUT[fmt];
  const h = L.phoneW * 16 / 9;
  const rise = enter ? spring({frame, fps, config: {damping: 20, stiffness: 120}}) : 1;
  const z = interpolate(frame, [0, durationInFrames], zoom, {...clamp, easing: Easing.bezier(0.33, 0, 0.2, 1)});
  return (
    <div style={{position: 'absolute', left: (L.w - L.phoneW) / 2, top: L.phoneTop + (1 - rise) * 160, width: L.phoneW, height: h,
      borderRadius: L.phoneW * 0.085, border: `${Math.round(L.phoneW * 0.014)}px solid ${C.line2}`, overflow: 'hidden', background: C.bg,
      boxShadow: '0 40px 120px rgba(0,0,0,.55)', opacity: interpolate(rise, [0, 0.4], [0, 1], clamp)}}>
      <div style={{position: 'absolute', inset: 0, scale: String(z), transformOrigin: focus}}>
        <OffthreadVideo src={staticFile(`footage/${src}.mp4`)} startFrom={Math.round(from * fps)} playbackRate={rate} volume={volume}
          style={{width: '100%', height: '100%', objectFit: 'cover'}} />
      </div>
      {children}
    </div>
  );
};

// A tap ring, to show where a finger would press.
export const Tap = ({x, y, at}) => {
  const frame = useCurrentFrame();
  const t = frame - at;
  if (t < 0 || t > 18) return null;
  return <div style={{position: 'absolute', left: x - 40, top: y - 40, width: 80, height: 80, borderRadius: 999,
    border: `5px solid ${C.gold}`, opacity: interpolate(t, [0, 18], [1, 0]), scale: String(interpolate(t, [0, 18], [0.5, 1.5]))}} />;
};

// Big centred text on its own (hooks and beats between the screens).
export const Beat = ({children, fmt}) => (
  <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', padding: fmt === 'feed' ? '0 80px' : '0 84px'}}>{children}</AbsoluteFill>
);

// The last card: logo, headline, the free-to-start line and the button.
export const EndCard = ({fmt, headline, sub = 'Module 1 of every course is free. No card needed.'}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const L = LAYOUT[fmt];
  const pop = (d) => spring({frame: frame - d, fps, config: {damping: 15, stiffness: 170}});
  const feed = fmt === 'feed';
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', gap: feed ? 30 : 40, padding: '0 90px',
      paddingBottom: feed ? 0 : 120}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 22, scale: String(pop(0)), opacity: pop(0)}}>
        <Logo size={feed ? 84 : 100} />
        <span style={{fontSize: feed ? 58 : 68, fontWeight: 800, letterSpacing: '-0.03em'}}>The Guide</span>
      </div>
      <Words text={headline} delay={5} size={feed ? 92 : 110} />
      <div style={{fontSize: feed ? 36 : 42, fontWeight: 500, color: C.ink2, textAlign: 'center', lineHeight: 1.3,
        opacity: pop(14), translate: `0 ${(1 - pop(14)) * 24}px`}}>{sub}</div>
      <div style={{marginTop: feed ? 6 : 16, background: C.green, color: C.onGreen, fontWeight: 800, fontSize: feed ? 44 : 50,
        padding: feed ? '26px 64px' : '30px 76px', borderRadius: 999, scale: String(0.6 + 0.4 * pop(20)), opacity: pop(20)}}>Start free</div>
      <div style={{fontSize: feed ? 34 : 40, fontWeight: 700, color: C.green, opacity: pop(26)}}>theguide.company</div>
    </AbsoluteFill>
  );
};

// Music under everything: fades in, ducks where real narration plays, fades out at the end.
export const bedVolume = (fps, total, duck = []) => (f) => {
  let v = interpolate(f, [0, 8, total - 24, total], [0, 0.32, 0.32, 0], clamp);
  for (const [a, b] of duck) v *= interpolate(f, [a - 6, a, b, b + 6], [1, 0.25, 0.25, 1], clamp);
  return v;
};
