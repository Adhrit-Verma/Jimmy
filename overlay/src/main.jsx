import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MotionConfig } from "motion/react";
import "./index.css";
import App from "./App.jsx";
import Timeline from "./Timeline.jsx";
import Onboarding from "./Onboarding.jsx";

// One bundle, three windows: the transparent overlay, #timeline / #insights / #memory / #settings
// (D31, D41, D60), and the installed app's first run, #onboarding (D61).
const Page = location.hash.startsWith("#onboarding") ? Onboarding
  : /^#(timeline|insights|memory|settings)/.test(location.hash) ? Timeline : App;

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <MotionConfig reducedMotion="user">
      <Page />
    </MotionConfig>
  </StrictMode>,
);
