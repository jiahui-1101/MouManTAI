import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { DevApp } from './DevApp';

createRoot(document.getElementById('root')!).render(<StrictMode><DevApp /></StrictMode>);
