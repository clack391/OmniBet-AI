import React from 'react';
import { X, Trophy, Trash2 } from 'lucide-react';
import { useBetSlip } from '../context/BetSlipContext';

const BetSlipSidebar = () => {
    const { betSlip, removeFromSlip } = useBetSlip();

    if (betSlip.length === 0) {
        return null; // Or a minimized state
    }

    // Calculate total odds (simple multiplier)
    const totalOdds = betSlip.reduce((acc, bet) => acc * (bet.odds || 1.0), 1.0).toFixed(2);
    const potentialReturn = (10 * totalOdds).toFixed(2); // Assuming $10 stake unit

    return (
        <div className="fixed right-0 top-0 h-full w-80 bg-gray-900 border-l border-gray-800 shadow-2xl z-50 flex flex-col animate-slideLeft">
            <div className="p-4 border-b border-gray-800 bg-gray-800/50 flex justify-between items-center">
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                    <Trophy className="w-5 h-5 text-yellow-500" /> Bet Slip
                    <span className="bg-blue-600 text-xs rounded-full px-2 py-0.5">{betSlip.length}</span>
                </h2>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-3 custom-scrollbar">
                {betSlip.map((bet) => (
                    <div key={bet.match_id} className="bg-gray-800 rounded-lg p-3 border border-gray-700 relative group">
                        <button
                            onClick={() => removeFromSlip(bet.match_id)}
                            className="absolute top-2 right-2 text-gray-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
                        >
                            <X className="w-4 h-4" />
                        </button>
                        <div className="text-xs text-gray-400 mb-1">{bet.match}</div>
                        <div className="text-blue-300 font-bold">{bet.selection}</div>
                        <div className="text-xs text-green-400 mt-1 flex justify-between">
                            <span>Safe Bet</span>
                            <span className="font-mono bg-gray-900 px-1 rounded">@{bet.odds}</span>
                        </div>
                    </div>
                ))}
            </div>

            <div className="p-4 border-t border-gray-800 bg-gray-800/30">
                <div className="flex justify-between items-center mb-2 text-sm text-gray-400">
                    <span>Total Odds</span>
                    <span className="text-white font-mono">{totalOdds}</span>
                </div>
                <div className="flex justify-between items-center mb-4 text-sm text-gray-400">
                    <span>Est. Return ($10)</span>
                    <span className="text-green-400 font-bold font-mono">${potentialReturn}</span>
                </div>
                <button className="w-full bg-green-600 hover:bg-green-500 text-white font-bold py-3 rounded-lg transition-colors shadow-lg shadow-green-900/20">
                    Place Bet
                </button>
            </div>
        </div>
    );
};

export default BetSlipSidebar;
