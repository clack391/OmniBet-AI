import React, { useState } from 'react';
import { Bolt, Check, Plus, Trophy, TrendingUp, Users, DollarSign, Activity, Brain, X, Maximize2, ChevronDown, ChevronUp, ShieldCheck, ShieldAlert, Clock, Target } from 'lucide-react';
import { useBetSlip } from '../context/BetSlipContext';

const PredictionCard = ({ prediction }) => {
    const { betSlip, addToSlip } = useBetSlip();
    const isAdded = betSlip.some(bet => bet.match_id === prediction.match_id);
    const [isHovered, setIsHovered] = useState(false);
    const [activeInsight, setActiveInsight] = useState(null); // Track which insight is open in modal
    const [showLogic, setShowLogic] = useState(false); // Toggle for AI step-by-step logic

    // Parse teams safely
    const [homeTeam, awayTeam] = prediction.match.split(' vs ');

    const handleAdd = () => {
        const bet = {
            match_id: prediction.match_id || Math.random(),
            match: prediction.match,
            selection: prediction.safe_bet_tip,
            odds: 1.85 // Mock odds as placeholder if not in data
        };
        addToSlip(bet);
    };

    // Helper to get insight icon
    const getMarketIcon = (market) => {
        if (market.includes('1X2') || market.includes('Winner')) return <Trophy className="w-4 h-4 text-yellow-400" />;
        if (market.includes('Goals') || market.includes('Over')) return <Activity className="w-4 h-4 text-blue-400" />;
        if (market.includes('BTTS')) return <TrendingUp className="w-4 h-4 text-accent-green" />;
        if (market.includes('Half') || market.includes('HT')) return <Clock className="w-4 h-4 text-orange-400" />;
        if (market.includes('Score') || market.includes('Exact')) return <Target className="w-4 h-4 text-red-400" />;
        return <Bolt className="w-4 h-4 text-accent-purple" />;
    };

    if (prediction.error) {
        return (
            <div className="bg-card-dark rounded-xl p-6 shadow-lg border border-red-900/50 animate-fadeIn">
                <div className="flex items-center gap-2 text-red-400">
                    <Activity className="w-5 h-5" />
                    <span>Error analyzing match {prediction.match_id}: {prediction.error}</span>
                </div>
            </div>
        );
    }

    return (
        <>
            <div
                className="relative overflow-hidden rounded-2xl bg-card-dark border border-slate-700/50 shadow-2xl transition-all duration-300 hover:scale-[1.01] hover:shadow-primary/10"
                onMouseEnter={() => setIsHovered(true)}
                onMouseLeave={() => setIsHovered(false)}
            >
                {/* Background Gradient Decorations */}
                <div className={`absolute -top-20 -right-20 w-64 h-64 bg-primary/20 rounded-full blur-[80px] pointer-events-none transition-opacity duration-500 ${isHovered ? 'opacity-100' : 'opacity-60'}`}></div>
                <div className="absolute top-40 -left-20 w-48 h-48 bg-accent-green/10 rounded-full blur-[60px] pointer-events-none"></div>

                {/* Card Header: Teams & Logo */}
                <div className="relative z-10 p-6 pb-4">
                    <div className="flex justify-between items-center mb-6">
                        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 bg-slate-800/50 px-3 py-1 rounded-full">
                            Match • Prediction
                        </span>
                        <div className="flex gap-2">
                            {/* Risk Manager Badge */}
                            {prediction.is_downgraded !== undefined && (
                                <div className={`flex items-center gap-1.5 px-3 py-1 rounded-full border ${prediction.is_downgraded ? 'bg-orange-500/10 border-orange-500/30 text-orange-400' : 'bg-blue-500/10 border-blue-500/30 text-blue-400'}`}>
                                    {prediction.is_downgraded ? <ShieldAlert className="w-4 h-4" /> : <ShieldCheck className="w-4 h-4" />}
                                    <span className="text-[10px] font-bold uppercase tracking-wide">
                                        {prediction.is_downgraded ? "Risk Manager Downgraded" : "Risk Manager Verified"}
                                    </span>
                                </div>
                            )}

                            {/* Confidence Badge */}
                            <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-accent-green/10 border border-accent-green/20 glow-green">
                                <Bolt className="w-4 h-4 text-accent-green" />
                                <span className="text-xs font-bold text-accent-green uppercase tracking-wide">{prediction.confidence}% Confidence</span>
                            </div>
                        </div>
                    </div>

                    {/* Teams Display */}
                    <div className="flex items-center justify-between gap-4">
                        {/* Home Team */}
                        <div className="flex flex-col items-center gap-3 flex-1">
                            <div className="relative">
                                <div className="w-16 h-16 rounded-full bg-slate-800 flex items-center justify-center border-2 border-slate-700 shadow-lg overflow-hidden group p-2 bg-white">
                                    {prediction.home_logo ? (
                                        <img src={prediction.home_logo} alt={homeTeam} className="w-full h-full object-contain drop-shadow-sm" />
                                    ) : (
                                        <span className="text-lg font-bold text-slate-500 group-hover:text-slate-800 transition-colors">{homeTeam?.substring(0, 2).toUpperCase()}</span>
                                    )}
                                </div>
                            </div>
                            <div className="text-center">
                                <h3 className="text-lg font-extrabold text-white leading-tight break-words max-w-[120px]">{homeTeam}</h3>
                                <p className="text-sm text-slate-400 font-medium">Home</p>
                            </div>
                        </div>

                        {/* VS Divider */}
                        <div className="flex flex-col items-center justify-center pt-2">
                            <span className="text-2xl font-black text-slate-600 italic">VS</span>
                        </div>

                        {/* Away Team */}
                        <div className="flex flex-col items-center gap-3 flex-1">
                            <div className="relative">
                                <div className="w-16 h-16 rounded-full bg-slate-800 flex items-center justify-center border-2 border-slate-700 shadow-lg overflow-hidden group p-2 bg-white">
                                    {prediction.away_logo ? (
                                        <img src={prediction.away_logo} alt={awayTeam} className="w-full h-full object-contain drop-shadow-sm" />
                                    ) : (
                                        <span className="text-lg font-bold text-slate-500 group-hover:text-slate-800 transition-colors">{awayTeam?.substring(0, 2).toUpperCase()}</span>
                                    )}
                                </div>
                            </div>
                            <div className="text-center">
                                <h3 className="text-lg font-extrabold text-white leading-tight break-words max-w-[120px]">{awayTeam}</h3>
                                <p className="text-sm text-slate-400 font-medium">Away</p>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Primary Expert Pick Section */}
                <div className="relative z-10 px-6 py-2">
                    <div className="bg-slate-800/40 border border-white/5 rounded-xl p-5 glass-panel">
                        <div className="flex justify-between items-start mb-2">
                            <div className="flex flex-col">
                                <span className="text-primary text-xs font-bold uppercase tracking-wider mb-1">AI Expert Pick</span>
                                <div className="flex items-baseline gap-2">
                                    <h1 className="text-2xl font-black text-white tracking-tight">{prediction.safe_bet_tip}</h1>
                                </div>
                            </div>
                            <div className="flex items-center gap-1">
                                <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse"></span>
                                <span className="text-[10px] text-red-400 font-bold uppercase">Live Analysis</span>
                            </div>
                        </div>
                        <div className="mt-4">
                            <button
                                onClick={handleAdd}
                                disabled={isAdded}
                                className={`group w-full h-12 flex items-center justify-center gap-2 transition-all duration-200 rounded-lg shadow-lg font-bold text-base ${isAdded ? 'bg-accent-green/20 text-accent-green cursor-default' : 'bg-primary hover:bg-primary/90 active:scale-[0.98] glow-primary text-white'}`}
                            >
                                {isAdded ? <Check className="w-5 h-5" /> : <Plus className="w-5 h-5 group-hover:hidden" />}
                                <span>{isAdded ? 'Bet Added' : 'Add to Slip'}</span>
                            </button>
                        </div>
                    </div>
                </div>

                {/* Market Insights Grid (Using full_analysis) */}
                <div className="relative z-10 p-6 pt-4">
                    <h4 className="text-sm font-bold text-slate-300 mb-3 flex items-center gap-2">
                        <Activity className="w-4 h-4 text-accent-purple" />
                        Market Insights (Click to Expand)
                    </h4>
                    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
                        {/* Render all 8 items as Insight Cards */}
                        {Object.entries(prediction.full_analysis || {}).map(([market, analysis], i) => (
                            <InsightCard
                                key={market}
                                market={market}
                                analysis={analysis}
                                index={i}
                                getIcon={getMarketIcon}
                                onClick={() => setActiveInsight({ market, analysis })}
                            />
                        ))}
                    </div>

                    {/* Reasoning Section - Adjusted title since cards also have reasoning */}
                    <div className="bg-slate-900/50 rounded-xl p-5 border-t border-slate-800">
                        <h4 className="text-sm font-bold text-white mb-3 flex items-center gap-2">
                            <Brain className="w-4 h-4 text-primary" />
                            Overall Strategy
                        </h4>
                        <ul className="space-y-3">
                            {(Array.isArray(prediction.reasoning) ? prediction.reasoning : [prediction.reasoning]).map((r, idx) => (
                                <li key={idx} className="flex gap-3 text-sm text-slate-300 leading-relaxed">
                                    <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-primary shrink-0"></span>
                                    <span>{r}</span>
                                </li>
                            ))}
                        </ul>
                    </div>

                    {/* AI Logic Dropdown (CoT) */}
                    {prediction.step_by_step_reasoning && (
                        <div className="mt-4 bg-slate-800/20 rounded-xl border border-slate-700/50 overflow-hidden transition-all duration-300">
                            <button
                                onClick={() => setShowLogic(!showLogic)}
                                className="w-full px-5 py-4 flex items-center justify-between hover:bg-slate-800/40 transition-colors"
                            >
                                <div className="flex items-center gap-2">
                                    <Bolt className="w-4 h-4 text-slate-400" />
                                    <span className="text-sm font-semibold text-slate-300">View AI Internal Logic</span>
                                </div>
                                {showLogic ? (
                                    <ChevronUp className="w-4 h-4 text-slate-400" />
                                ) : (
                                    <ChevronDown className="w-4 h-4 text-slate-400" />
                                )}
                            </button>

                            {/* Expandable Content */}
                            <div className={`transition-all duration-300 ease-in-out ${showLogic ? 'max-h-[500px] opacity-100 p-5 pt-0' : 'max-h-0 opacity-0 overflow-hidden'}`}>
                                <div className="pt-4 border-t border-slate-700/50">
                                    <p className="text-sm text-slate-400 leading-relaxed whitespace-pre-wrap font-mono bg-black/20 p-4 rounded-lg">
                                        {prediction.step_by_step_reasoning}
                                    </p>
                                </div>
                            </div>
                        </div>
                    )}
                </div>

                {/* Bottom decorative bar */}
                <div className="h-1.5 w-full bg-gradient-to-r from-primary via-accent-purple to-accent-green"></div>
            </div>

            {/* Modal for Expanded Insight */}
            {activeInsight && (
                <InsightModal
                    market={activeInsight.market}
                    analysis={activeInsight.analysis}
                    onClose={() => setActiveInsight(null)}
                    getIcon={getMarketIcon}
                />
            )}
        </>
    );
};

// Simplified Card Component (Triggers Modal)
const InsightCard = ({ market, analysis, index, getIcon, onClick }) => {
    // Basic Parsing for Preview
    const parts = analysis.split('. ');
    const predictionText = parts[0]?.replace('Prediction: ', '').replace('Prediction:', '') || 'N/A';

    return (
        <div
            onClick={onClick}
            className="group cursor-pointer bg-slate-800/30 border border-slate-700/50 rounded-xl p-3 flex flex-col justify-between hover:bg-slate-800/80 hover:border-primary/50 transition-all duration-300 hover:scale-[1.02] hover:shadow-lg hover:shadow-primary/10 h-24"
        >
            <div className="flex justify-between items-start">
                <p className={`text-[10px] font-bold uppercase tracking-wide ${index % 2 === 0 ? 'text-accent-purple' : 'text-accent-green'}`}>
                    {market.replace(/_/g, " ")}
                </p>
                <div className="p-1 rounded-full bg-slate-700/50 group-hover:bg-primary/20 transition-colors">
                    <Maximize2 className="w-3 h-3 text-slate-400 group-hover:text-primary" />
                </div>
            </div>

            <div className="flex items-center justify-between gap-1 mt-auto">
                <p className="text-sm font-bold text-white leading-tight line-clamp-2">
                    {predictionText}
                </p>
                {getIcon(market)}
            </div>
        </div>
    );
};

// Pop-out Modal Component
const InsightModal = ({ market, analysis, onClose, getIcon }) => {
    // Detailed Parsing
    const parts = analysis.split('. ');
    const predictionText = parts[0]?.replace('Prediction: ', '').replace('Prediction:', '') || 'N/A';
    const reasoningText = parts.slice(1).join('. ') || 'No detailed reasoning provided.';

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            {/* Backdrop */}
            <div
                className="absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity"
                onClick={onClose}
            ></div>

            {/* Modal Content */}
            <div className="relative w-full max-w-lg bg-card-dark border border-slate-700 rounded-2xl shadow-2xl overflow-hidden glass-panel animate-in fade-in zoom-in duration-200">
                {/* Header */}
                <div className="flex items-center justify-between p-6 border-b border-slate-700/50 bg-slate-800/50">
                    <div className="flex items-center gap-3">
                        <div className="p-2 rounded-lg bg-slate-700/50">
                            {getIcon(market)}
                        </div>
                        <div>
                            <p className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                                {market.replace(/_/g, " ")}
                            </p>
                            <h3 className="text-xl font-black text-white">
                                {predictionText}
                            </h3>
                        </div>
                    </div>
                    <button
                        onClick={onClose}
                        className="p-2 rounded-full hover:bg-slate-700/50 text-slate-400 hover:text-white transition-colors"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>

                {/* Body */}
                <div className="p-6">
                    <div className="flex items-start gap-4">
                        <div className="mt-1">
                            <Brain className="w-5 h-5 text-primary" />
                        </div>
                        <div className="space-y-4">
                            <h4 className="text-sm font-bold text-white">Detailed Analysis</h4>
                            <p className="text-base text-slate-300 leading-relaxed">
                                {reasoningText}
                            </p>
                        </div>
                    </div>
                </div>

                {/* Footer */}
                <div className="flex justify-end p-4 border-t border-slate-700/50 bg-slate-800/30">
                    <button
                        onClick={onClose}
                        className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white text-sm font-bold rounded-lg transition-colors"
                    >
                        Close Analysis
                    </button>
                </div>
            </div>
        </div>
    );
};

export default PredictionCard;
