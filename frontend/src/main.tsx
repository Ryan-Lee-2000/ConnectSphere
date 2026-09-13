import React from 'react';
import { createRoot } from 'react-dom/client';
import { domAnimation, LazyMotion, MotionConfig } from 'motion/react';
import { App } from './App';
import './style.css';

createRoot(document.getElementById('root')!).render(<React.StrictMode><LazyMotion features={domAnimation} strict><MotionConfig reducedMotion="user"><App /></MotionConfig></LazyMotion></React.StrictMode>);
