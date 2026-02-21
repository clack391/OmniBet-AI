import React, { createContext, useContext, useState } from 'react';

const BetSlipContext = createContext();

export const useBetSlip = () => useContext(BetSlipContext);

export const BetSlipProvider = ({ children }) => {
    const [betSlip, setBetSlip] = useState([]);

    const addToSlip = (bet) => {
        // Avoid duplicates
        if (!betSlip.some(b => b.match_id === bet.match_id)) {
            setBetSlip([...betSlip, bet]);
        }
    };

    const removeFromSlip = (matchId) => {
        setBetSlip(betSlip.filter(bet => bet.match_id !== matchId));
    };

    return (
        <BetSlipContext.Provider value={{ betSlip, addToSlip, removeFromSlip }}>
            {children}
        </BetSlipContext.Provider>
    );
};
