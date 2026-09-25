import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App.jsx";
import Timeline from "./Timeline.jsx";

// One bundle, two windows: the transparent overlay, and #timeline (Stage 5).
const Page = location.hash.startsWith("#timeline") ? Timeline : App;

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <Page />
  </StrictMode>,
);
