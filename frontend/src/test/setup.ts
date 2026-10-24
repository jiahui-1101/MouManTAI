import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/react";

// React Query state transitions can exceed Testing Library's 1s default under parallel CI load.
configure({ asyncUtilTimeout: 5000 });
