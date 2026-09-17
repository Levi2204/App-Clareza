import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import Desktop from './Desktop';
import '@fontsource-variable/dm-sans';
import '@fontsource-variable/manrope';
import { PrivacyProvider } from './PrivacyContext';
import './styles.css';
createRoot(document.getElementById('root')).render(<PrivacyProvider><Desktop><App /></Desktop></PrivacyProvider>);
