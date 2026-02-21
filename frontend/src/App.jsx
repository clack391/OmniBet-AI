import React from 'react';
import Dashboard from './components/Dashboard';
import { BetSlipProvider } from './context/BetSlipContext';
import BetSlipSidebar from './components/BetSlipSidebar';

function App() {
  return (
    <BetSlipProvider>
      <div className="flex">
        <div className="flex-1">
          <Dashboard />
        </div>
        <BetSlipSidebar />
      </div>
    </BetSlipProvider>
  );
}

export default App;
