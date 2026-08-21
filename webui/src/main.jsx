import React from "react";
import { createRoot } from "react-dom/client";
import "computer-modern/cmu-sans-serif.css";
import "computer-modern/cmu-serif.css";
import "computer-modern/cmu-typewriter-text.css";
import { App } from "./App.jsx";
import "./styles.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
