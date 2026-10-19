import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {Ad01, AD01_SECONDS, Ad02, AD02_SECONDS, Ad03, AD03_SECONDS, Ad04, AD04_SECONDS} from './ads';

// One composition per ad and format. The id is the file name it renders to in ads/creatives/.
const ADS = [
  ['ad01-i-watched-47-videos', Ad01, AD01_SECONDS],
  ['ad02-ai-mentor', Ad02, AD02_SECONDS],
  ['ad03-stop-scrolling', Ad03, AD03_SECONDS],
  ['ad04-course-vs-the-guide', Ad04, AD04_SECONDS],
];

const Root = () => (
  <>
    {ADS.map(([id, Comp, sec]) => (
      <React.Fragment key={id}>
        <Composition id={`${id}-v2-story-9x16`} component={Comp} defaultProps={{fmt: 'story'}} durationInFrames={Math.round(sec * 30)} fps={30} width={1080} height={1920} />
        <Composition id={`${id}-v2-feed-4x5`} component={Comp} defaultProps={{fmt: 'feed'}} durationInFrames={Math.round(sec * 30)} fps={30} width={1080} height={1350} />
      </React.Fragment>
    ))}
  </>
);

registerRoot(Root);
