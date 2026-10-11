import { Composition } from "remotion";
import { ArchipelagoLoop } from "./ArchipelagoLoop";
import { DURATION_S, FPS, H, SCALE, W } from "./world/paths";

export const RemotionRoot: React.FC = () => (
  <Composition
    id="ArchipelagoLoop"
    component={ArchipelagoLoop}
    durationInFrames={DURATION_S * FPS}
    fps={FPS}
    width={W * SCALE}
    height={H * SCALE}
  />
);
