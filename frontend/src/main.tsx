import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';
import { mostraTema, temaAttuale } from './tema';

// L'attributo l'ha gia' messo index.html; qui si allinea la barra del browser.
mostraTema(temaAttuale());

const rootElement = document.getElementById('root');
if (rootElement) {
  ReactDOM.createRoot(rootElement).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
}
