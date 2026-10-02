import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MotionConfig } from "motion/react";
import "./index.css";
import App from "./App.jsx";
import Timeline from "./Timeline.jsx";

// One bundle, two windows: the transparent overlay, and #timeline / #insights (Stage 5, D31).
const Page = /^#(timeline|insights)/.test(location.hash) ? Timeline : App;

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <MotionConfig reducedMotion="user">
      <Page />
    </MotionConfig>
  </StrictMode>,
);
