import React, { useState } from 'react';
import { Bolt, Check, Plus, Trophy, TrendingUp, Users, DollarSign, Activity, Brain, X, Maximize2, ChevronDown, ChevronUp, ShieldCheck, ShieldAlert, Clock, Target, Flag, AlertTriangle, User, Scale, Gavel, Share2, MapPin, Loader2, Info, CheckCircle2, XCircle, Shield, BarChart2 } from 'lucide-react';
import SupremeCourtCard from './SupremeCourtCard';
import { useBetSlip } from '../context/BetSlipContext';

const PredictionCard = ({ prediction }) => {
    const { betSlip, addToSlip } = useBetSlip();
    const isAdded = betSlip.some(bet => bet.match_id === prediction.match_id);
    const [isHovered, setIsHovered] = useState(false);
    const [activeInsight, setActiveInsight] = useState(null); // Track which insight is open in modal
    const [showLogic, setShowLogic] = useState(false); // Toggle for AI step-by-step logic

    // === Rule 40 Warning Detection ===
    // Scan all available supreme court text for Early-Season Quarantine or Desperation Grind signals.
    const rule40Text = [
        prediction.supreme_court?.ruling_text,
        prediction.supreme_court?.Internal_Logic_Override,
        prediction.supreme_court?.Overall_Strategy_Override,
    ].filter(Boolean).join(' ').toLowerCase();

    const isEarlySeasonQuarantine = (
        rule40Text.includes('rule 40') ||
        rule40Text.includes('early-season quarantine') ||
        rule40Text.includes('early season quarantine') ||
        rule40Text.includes('fewer than 5') ||
        rule40Text.includes('less than 5 match') ||
        rule40Text.includes('small sample') ||
        rule40Text.includes('sample size quarantine') ||
        rule40Text.includes('extreme variance veto')
    );

    const isDesperationGrind = (
        rule40Text.includes('desperation grind') ||
        rule40Text.includes('bottom-feeder') ||
        rule40Text.includes('bottom feeder') ||
        rule40Text.includes('winless') ||
        (rule40Text.includes('relegation') && rule40Text.includes('grind'))
    );

    const hasRule40Warning = isEarlySeasonQuarantine || isDesperationGrind;

    // Parse teams safely
    const [homeTeam, awayTeam] = (prediction.match || "Unknown vs Unknown").split(' vs ');

    const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

    const getLogoUrl = (logoPath) => {
        if (!logoPath) return null;
        if (logoPath.startsWith('http') || logoPath.startsWith(API_URL)) return logoPath;
        // Strip leading slash if API_URL ends with one (unlikely but safe)
        const path = logoPath.startsWith('/') ? logoPath : `/${logoPath}`;
        return `${API_URL}${path}`;
    };

    const handleAdd = (pickObj, type) => {
        // Fallback for legacy predictions still using safe_bet_tip string
        const tipStr = typeof pickObj === 'string' ? pickObj : pickObj?.tip;
        if (!tipStr) return;

        // Try to find real market odds from the odds_data payload
        let extractedOdds = typeof pickObj === 'object' && pickObj?.odds ? parseFloat(pickObj.odds) : null;

        if (!extractedOdds) {
            extractedOdds = findMarketOdds(tipStr);
        }

        // Final AI fallback if no market odds found
        const aiFallbackOdds = typeof pickObj === 'object' && pickObj?.odds ? parseFloat(pickObj.odds) :
            (type === 'Value' ? 2.50 : 1.85);

        const bet = {
            match_id: prediction.match_id || Math.random(),
            match: prediction.match,
            match_date: prediction.match_date,
            selection: tipStr,
            market: typeof pickObj === 'object' ? pickObj?.market : '',
            type: type, // 'Primary' or 'Value'
            odds: extractedOdds || aiFallbackOdds
        };
        addToSlip(bet);
    };

    const findMarketOdds = (tip) => {
        if (!prediction.odds_data || !tip) return null;
        const normalizedTip = tip.toLowerCase().replace(/[\s\-_]/g, '');

        // Flatten all outcomes from all bookmakers and markets
        const allOutcomes = [];
        prediction.odds_data.forEach(bookie => {
            bookie.markets?.forEach(market => {
                market.outcomes?.forEach(outcome => {
                    allOutcomes.push({
                        name: outcome.name,
                        price: outcome.price,
                        point: outcome.point,
                        market: market.key
                    });
                });
            });
        });

        // Smart Matching
        for (const outcome of allOutcomes) {
            const name = outcome.name?.toLowerCase() || '';

            // 1. Exact Name Match (e.g. "Real Madrid")
            if (normalizedTip.includes(name.replace(/\s/g, ''))) return outcome.price;

            // 2. Over/Under Point Match (e.g. "Over 2.5 Goals" vs name="Over", point=2.5)
            if (outcome.point) {
                if (normalizedTip.includes('over') && name.includes('over') && normalizedTip.includes(outcome.point.toString())) return outcome.price;
                if (normalizedTip.includes('under') && name.includes('under') && normalizedTip.includes(outcome.point.toString())) return outcome.price;
            }

            // 3. Draw Match
            if (normalizedTip.includes('draw') && name.includes('draw')) return outcome.price;

            // 4. BTTS (Yes/No)
            if (normalizedTip.includes('btts') || normalizedTip.includes('bothteams')) {
                if (normalizedTip.includes('yes') && name.includes('yes')) return outcome.price;
                if (normalizedTip.includes('no') && name.includes('no')) return outcome.price;
            }
        }
        return null;
    };

    // Helper to check if a specific pick is added
    const isPickAdded = (tipStr) => {
        return betSlip.some(bet => bet.match_id === prediction.match_id && bet.selection === tipStr);
    };

    // Helper to get insight icon
    const getMarketIcon = (market) => {
        if (market.includes('1X2') || market.includes('Winner')) return <Trophy className="w-4 h-4 text-yellow-400" />;
        if (market.includes('Goals') || market.includes('Over')) return <Activity className="w-4 h-4 text-blue-400" />;
        if (market.includes('BTTS')) return <TrendingUp className="w-4 h-4 text-accent-green" />;
        if (market.includes('Half') || market.includes('HT') || market.includes('Minute')) return <Clock className="w-4 h-4 text-orange-400" />;
        if (market.includes('Score') || market.includes('Exact')) return <Target className="w-4 h-4 text-red-400" />;
        if (market.includes('Corner')) return <Flag className="w-4 h-4 text-cyan-400" />;
        if (market.includes('Card') || market.includes('Booking')) return <AlertTriangle className="w-4 h-4 text-amber-500" />;
        if (market.includes('Player') || market.includes('Prop')) return <User className="w-4 h-4 text-emerald-400" />;
        return <Bolt className="w-4 h-4 text-accent-purple" />;
    };

    if (prediction.error) {
        return (
            <div className="bg-red-950/20 border-2 border-red-500/50 rounded-2xl p-8 shadow-2xl animate-fadeIn text-center flex flex-col items-center gap-4">
                <div className="bg-red-500/20 p-4 rounded-full border border-red-500/30">
                    <ShieldAlert className="w-12 h-12 text-red-500" />
                </div>
                <div>
                    <h3 className="text-xl font-black text-white uppercase tracking-tighter mb-2">Analysis Failed</h3>
                    <p className="text-red-300/80 text-sm max-w-md mx-auto leading-relaxed">
                        We encountered a problem fetching data for {prediction.match || "this match"}.
                        <span className="block mt-2 font-bold text-red-400">
                            {prediction.error.includes("Timeout")
                                ? "The provider is currently congested. Please wait 10 seconds and try again."
                                : prediction.error}
                        </span>
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <div className="text-[10px] font-black text-red-500 uppercase tracking-widest bg-red-500/10 px-3 py-1 rounded-full border border-red-500/20">
                        Infrastructure Error #SS-500
                    </div>
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
                <div className="relative z-10 p-4 md:p-6 pb-4">
                    <div className="flex justify-between items-center mb-6">
                        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 bg-slate-800/50 px-3 py-1 rounded-full">
                            Match • Prediction
                        </span>
                        <div className="flex flex-wrap gap-2">
                            {/* Risk Manager Badge */}
                            {prediction.is_downgraded !== undefined && (
                                <div className={`flex items-center gap-1.5 px-3 py-1 rounded-full border ${prediction.is_downgraded ? 'bg-orange-500/10 border-orange-500/30 text-orange-400' : 'bg-blue-500/10 border-blue-500/30 text-blue-400'}`}>
                                    {prediction.is_downgraded ? <ShieldAlert className="w-4 h-4" /> : <ShieldCheck className="w-4 h-4" />}
                                    <span className="text-[10px] font-bold uppercase tracking-wide">
                                        {prediction.is_downgraded ? "Risk Manager Downgraded" : "Risk Manager Verified"}
                                    </span>
                                </div>
                            )}

                            {/* Rule 40: Early-Season Quarantine Badge */}
                            {isEarlySeasonQuarantine && (
                                <div className="flex items-center gap-1.5 px-3 py-1 rounded-full border bg-yellow-500/10 border-yellow-500/40 text-yellow-400">
                                    <AlertTriangle className="w-4 h-4" />
                                    <span className="text-[10px] font-bold uppercase tracking-wide">Early-Season Quarantine</span>
                                </div>
                            )}

                            {/* Rule 40: Desperation Grind Badge */}
                            {!isEarlySeasonQuarantine && isDesperationGrind && (
                                <div className="flex items-center gap-1.5 px-3 py-1 rounded-full border bg-red-900/20 border-red-500/40 text-red-400">
                                    <AlertTriangle className="w-4 h-4" />
                                    <span className="text-[10px] font-bold uppercase tracking-wide">Desperation Grind</span>
                                </div>
                            )}

                        </div>
                    </div>

                    {/* Teams Display */}
                    <div className="flex items-center justify-between gap-2 md:gap-4 min-w-0">
                        {/* Home Team */}
                        <div className="flex flex-col items-center gap-2 md:gap-3 flex-1 min-w-0">
                            <div className="relative shrink-0">
                                <div className="w-14 h-14 md:w-16 md:h-16 rounded-full bg-slate-800 flex items-center justify-center border-2 border-slate-700 shadow-lg overflow-hidden group p-1.5 md:p-2 bg-white">
                                    {prediction.home_logo ? (
                                        <img src={getLogoUrl(prediction.home_logo)} alt={homeTeam} className="w-full h-full object-contain drop-shadow-sm shrink-0" />
                                    ) : (
                                        <span className="text-base md:text-lg font-bold text-slate-500 group-hover:text-slate-800 transition-colors shrink-0">{homeTeam?.substring(0, 2).toUpperCase()}</span>
                                    )}
                                </div>
                            </div>
                            <div className="text-center w-full min-w-0">
                                <h3 className="text-base md:text-lg font-extrabold text-white leading-tight truncate px-1">{homeTeam}</h3>
                                <p className="text-[10px] md:text-sm text-slate-400 font-medium whitespace-nowrap">Home</p>
                            </div>
                        </div>

                        {/* VS Divider */}
                        <div className="flex flex-col items-center justify-center pt-2 shrink-0">
                            <span className="text-lg md:text-2xl font-black text-slate-600 italic">VS</span>
                        </div>

                        {/* Away Team */}
                        <div className="flex flex-col items-center gap-2 md:gap-3 flex-1 min-w-0">
                            <div className="relative shrink-0">
                                <div className="w-14 h-14 md:w-16 md:h-16 rounded-full bg-slate-800 flex items-center justify-center border-2 border-slate-700 shadow-lg overflow-hidden group p-1.5 md:p-2 bg-white">
                                    {prediction.away_logo ? (
                                        <img src={getLogoUrl(prediction.away_logo)} alt={awayTeam} className="w-full h-full object-contain drop-shadow-sm shrink-0" />
                                    ) : (
                                        <span className="text-base md:text-lg font-bold text-slate-500 group-hover:text-slate-800 transition-colors shrink-0">{awayTeam?.substring(0, 2).toUpperCase()}</span>
                                    )}
                                </div>
                            </div>
                            <div className="text-center w-full min-w-0">
                                <h3 className="text-base md:text-lg font-extrabold text-white leading-tight truncate px-1">{awayTeam}</h3>
                                <p className="text-[10px] md:text-sm text-slate-400 font-medium whitespace-nowrap">Away</p>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Rule 40 Warning Banner — shown below team logos when active */}
                {hasRule40Warning && (
                    <div className={`mt-4 mx-4 mb-4 px-4 py-3 rounded-xl border flex items-start gap-3 ${isEarlySeasonQuarantine
                        ? 'bg-yellow-500/5 border-yellow-500/30'
                        : 'bg-red-500/5 border-red-500/20'
                        }`}>
                        <AlertTriangle className={`w-5 h-5 shrink-0 mt-0.5 ${isEarlySeasonQuarantine ? 'text-yellow-400' : 'text-red-400'}`} />
                        <div>
                            <p className={`text-xs font-black uppercase tracking-wider mb-0.5 ${isEarlySeasonQuarantine ? 'text-yellow-400' : 'text-red-400'}`}>
                                {isEarlySeasonQuarantine ? '⚠️ Rule 40 — Early-Season Quarantine Active' : '⚠️ Rule 40 — Desperation Grind Detected'}
                            </p>
                            <p className="text-[11px] text-slate-400 leading-relaxed">
                                {isEarlySeasonQuarantine
                                    ? 'One or both teams have played fewer than 5 matches. Precise goals markets (Over 2.5, Under 2.5, BTTS) are statistically unreliable. The AI evaluates four xG-anchored structural markets in priority order — Over 0.5, Under 3.5, Under 4.5, Over 1.5 — then falls back to Match Control on pedigree, or declares NO BET if no safe floor exists.'
                                    : 'Both teams are winless or in the relegation zone. GA averages are mirages from mismatched fixtures. High-scoring goals markets are structurally unsound for this low-quality grind.'}
                            </p>
                        </div>
                    </div>
                )}
            </div>

            {/* Agent 3: Supreme Court Ruling Component */}
            <div className="mx-6 mb-6">
                <SupremeCourtCard
                    supreme_court={prediction.supreme_court}
                    handleAdd={handleAdd}
                    isPickAdded={isPickAdded}
                />
            </div>

            {/* Dual Expert Picks Section */}
            < div className="relative z-10 px-6 py-2" >
                <div className="bg-slate-800/40 border border-white/5 rounded-xl p-5 glass-panel">
                    <div className="flex justify-between items-start mb-4">
                        <span className="text-primary text-xs font-bold uppercase tracking-wider">AI Expert Picks</span>
                        <div className="flex items-center gap-1">
                            {prediction.supreme_court?.verdict_status === 'NO_BET' ? (
                                <span className="text-[10px] text-zinc-500 font-bold uppercase flex items-center gap-1">
                                    <Shield className="w-3 h-3" /> Vetoed by court
                                </span>
                            ) : (
                                <>
                                    <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse"></span>
                                    <span className="text-[10px] text-red-400 font-bold uppercase">Live Analysis</span>
                                </>
                            )}
                        </div>
                    </div>

                    <div className={`grid grid-cols-1 md:grid-cols-2 gap-4 relative ${prediction.supreme_court?.verdict_status === 'NO_BET' ? 'opacity-40 grayscale pointer-events-none' : ''}`}>
                        {prediction.supreme_court?.verdict_status === 'NO_BET' && (
                            <div className="absolute inset-0 z-20 flex items-center justify-center">
                                <div className="bg-zinc-900/90 border border-zinc-500/30 px-4 py-2 rounded-full flex items-center gap-2 shadow-2xl backdrop-blur-sm">
                                    <ShieldAlert className="w-4 h-4 text-zinc-400" />
                                    <span className="text-xs font-bold text-zinc-300 uppercase tracking-widest">Judicial Veto: No Recommended Bet</span>
                                </div>
                            </div>
                        )}
                        {/* Primary Safe Pick */}
                        <div className="bg-slate-900/60 border border-emerald-500/20 rounded-lg p-4 flex flex-col justify-between">
                            <div>
                                <div className="flex items-center gap-2 mb-2">
                                    <ShieldCheck className="w-4 h-4 text-emerald-400" />
                                    <span className="text-emerald-400 text-[10px] font-bold uppercase tracking-wider">Primary Safe Bet</span>
                                </div>
                                <h2 className="text-lg font-black text-white leading-tight mb-2">
                                    {prediction.primary_pick?.tip || prediction.safe_bet_tip}
                                </h2>
                                <div className="flex items-center gap-2 mb-4">
                                    <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                                        <div
                                            className="h-full bg-emerald-500 rounded-full"
                                            style={{ width: `${prediction.primary_pick?.confidence || prediction.confidence || 0}%` }}
                                        ></div>
                                    </div>
                                    <span className="text-xs font-bold text-emerald-400">{prediction.primary_pick?.confidence || prediction.confidence}%</span>
                                    {prediction.primary_pick?.odds && (
                                        <span className="text-[10px] bg-emerald-500/20 text-emerald-300 px-1.5 py-0.5 rounded border border-emerald-500/30">
                                            @{prediction.primary_pick.odds}
                                        </span>
                                    )}
                                </div>
                            </div>

                            <button
                                onClick={() => handleAdd(prediction.primary_pick || prediction.safe_bet_tip, 'Primary')}
                                disabled={isPickAdded(prediction.primary_pick?.tip || prediction.safe_bet_tip) || prediction.supreme_court?.verdict_status === 'NO_BET'}
                                className={`w-full py-2.5 rounded-lg text-sm font-bold transition-all flex items-center justify-center gap-2 ${isPickAdded(prediction.primary_pick?.tip || prediction.safe_bet_tip)
                                    ? 'bg-emerald-500/10 text-emerald-500 cursor-default border border-emerald-500/20'
                                    : 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg shadow-emerald-900/20'
                                    }`}
                            >
                                {isPickAdded(prediction.primary_pick?.tip || prediction.safe_bet_tip) ? <Check className="w-4 h-4" /> : <Plus className="w-4 h-4" />}
                                <span>{isPickAdded(prediction.primary_pick?.tip || prediction.safe_bet_tip) ? 'Added' : 'Add Banker'}</span>
                            </button>
                        </div>

                        {/* Alternative Value Pick */}
                        {prediction.alternative_pick && (
                            <div className="bg-slate-900/60 border border-amber-500/20 rounded-lg p-4 flex flex-col justify-between">
                                <div>
                                    <div className="flex items-center gap-2 mb-2">
                                        <Target className="w-4 h-4 text-amber-400" />
                                        <span className="text-amber-400 text-[10px] font-bold uppercase tracking-wider">Value Alternative</span>
                                    </div>
                                    <h2 className="text-lg font-black text-white leading-tight mb-2">
                                        {prediction.alternative_pick.tip}
                                    </h2>
                                    <div className="flex items-center gap-2 mb-4">
                                        <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                                            <div
                                                className="h-full bg-amber-500 rounded-full"
                                                style={{ width: `${prediction.alternative_pick.confidence}%` }}
                                            ></div>
                                        </div>
                                        <span className="text-xs font-bold text-amber-400">{prediction.alternative_pick.confidence}%</span>
                                        {prediction.alternative_pick?.odds && (
                                            <span className="text-[10px] bg-amber-500/20 text-amber-300 px-1.5 py-0.5 rounded border border-amber-500/30">
                                                @{prediction.alternative_pick.odds}
                                            </span>
                                        )}
                                    </div>
                                </div>

                                <button
                                    onClick={() => handleAdd(prediction.alternative_pick, 'Value')}
                                    disabled={isPickAdded(prediction.alternative_pick.tip) || prediction.supreme_court?.verdict_status === 'NO_BET'}
                                    className={`w-full py-2.5 rounded-lg text-sm font-bold transition-all flex items-center justify-center gap-2 ${isPickAdded(prediction.alternative_pick.tip)
                                        ? 'bg-amber-500/10 text-amber-500 cursor-default border border-amber-500/20'
                                        : 'bg-amber-600 hover:bg-amber-500 text-white shadow-lg shadow-amber-900/20'
                                        }`}
                                >
                                    {isPickAdded(prediction.alternative_pick.tip) ? <Check className="w-4 h-4" /> : <Plus className="w-4 h-4" />}
                                    <span>{isPickAdded(prediction.alternative_pick.tip) ? 'Added' : 'Add Value Bet'}</span>
                                </button>
                            </div>
                        )}
                    </div>
                </div>
            </div >

            {/* Market Insights Grid (Using full_analysis) */}
            < div className="relative z-10 p-6 pt-4" >
                <h4 className="text-sm font-bold text-slate-300 mb-3 flex items-center gap-2">
                    <Activity className="w-4 h-4 text-accent-purple" />
                    Market Insights (Click to Expand)
                </h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
                    {/* Render all items as Insight Cards, merging Supreme Court corrections */}
                    {Object.entries({
                        ...(prediction.full_analysis || {}),
                        ...(prediction.supreme_court?.grid_corrections || {})
                    }).map(([market, analysis], i) => {
                        const isCorrection = !!(prediction.supreme_court?.grid_corrections?.[market]);
                        return (
                            <InsightCard
                                key={market}
                                market={market}
                                analysis={analysis}
                                index={i}
                                isCorrection={isCorrection}
                                getIcon={getMarketIcon}
                                onClick={() => setActiveInsight({ market, analysis, isCorrection })}
                            />
                        );
                    })}
                </div>

                {/* Reasoning Section - Adjusted title since cards also have reasoning */}
                <div className="bg-slate-900/50 rounded-xl p-5 border-t border-slate-800">
                    <h4 className="text-sm font-bold text-white mb-3 flex items-center gap-2">
                        <Brain className="w-4 h-4 text-primary" />
                        Overall Strategy
                        {prediction.supreme_court?.Overall_Strategy_Override && (
                            <span className="ml-2 px-2 py-0.5 bg-accent-purple/20 text-accent-purple text-[10px] uppercase font-bold rounded border border-accent-purple/30">
                                SUPREME COURT OVERRIDE
                            </span>
                        )}
                    </h4>
                    <ul className="space-y-3">
                        {(prediction.supreme_court?.Overall_Strategy_Override
                            ? [prediction.supreme_court.Overall_Strategy_Override]
                            : (Array.isArray(prediction.reasoning) ? prediction.reasoning : [prediction.reasoning])).map((r, idx) => (
                                <li key={idx} className="flex gap-3 text-sm text-slate-300 leading-relaxed">
                                    <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-primary shrink-0"></span>
                                    <span>{r}</span>
                                </li>
                            ))}
                    </ul>
                </div>

                {/* Game State Simulation (New Phase 9) */}
                {
                    prediction.scenario_analysis && (
                        <div className="bg-slate-900/50 rounded-xl p-5 border-t border-slate-800 mt-4">
                            <h4 className="text-sm font-bold text-white mb-3 flex items-center gap-2">
                                <Target className="w-4 h-4 text-orange-400" />
                                Game State Simulation
                            </h4>

                            {prediction.supreme_court?.simulation_data && (
                                <div className="mb-5 p-4 bg-slate-950/40 rounded-lg border border-amber-500/20">
                                    <h5 className="text-[10px] font-bold text-amber-500/70 uppercase tracking-widest mb-3 flex items-center gap-2">
                                        <BarChart2 className="w-3 h-3" /> 10,000 Monte Carlo Variations (Goal Distribution)
                                    </h5>

                                    {/* Simulation Audit String - Parameters Display */}
                                    {prediction.supreme_court?.simulation_audit && (
                                        <div className="mb-4 p-4 bg-gradient-to-br from-amber-950/40 to-orange-950/40 rounded-lg border-2 border-amber-500/30 shadow-lg shadow-amber-500/10">
                                            <div className="flex items-start gap-3">
                                                <Info className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
                                                <div className="flex-1">
                                                    <h6 className="text-[10px] font-black text-amber-400 uppercase tracking-wider mb-2 flex items-center gap-2">
                                                        🔬 Simulation Parameters
                                                    </h6>
                                                    <p className="text-xs font-mono text-amber-300/90 leading-relaxed break-words">
                                                        {prediction.supreme_court.simulation_audit}
                                                    </p>
                                                </div>
                                            </div>
                                        </div>
                                    )}

                                    <div className="flex items-end gap-2 h-20 w-full mt-2 relative">
                                        {Object.entries(prediction.supreme_court.simulation_data).map(([goals, count]) => {
                                            const height = Math.max(5, (count / 10000) * 100);
                                            return (
                                                <div key={goals} className="flex-1 h-full flex flex-col items-center justify-end group py-px relative">
                                                    <span className="text-[9px] text-amber-300 font-mono opacity-0 group-hover:opacity-100 transition-opacity font-bold absolute -top-5">
                                                        {((count / 10000) * 100).toFixed(1)}%
                                                    </span>
                                                    <div
                                                        className="w-full bg-gradient-to-t from-orange-600/60 to-amber-400 rounded-t-sm transition-all duration-500 ease-out border-b border-amber-500/30 hover:brightness-125"
                                                        style={{ height: `${height}%` }}
                                                    ></div>
                                                    <span className="text-[10px] font-black text-slate-400 mt-2">{goals}</span>
                                                </div>
                                            );
                                        })}
                                    </div>
                                    <div className="text-[9px] text-center text-slate-500 font-black mt-2 uppercase tracking-wide">Total Match Goals</div>
                                    {prediction.supreme_court?.top_scorelines && prediction.supreme_court.top_scorelines.length > 0 && (
                                        <div className="mt-4 border-t border-amber-500/20 pt-3">
                                            <div className="text-[9px] text-amber-500/70 uppercase tracking-widest font-bold mb-2 text-center">Most Likely Per Goal Range</div>
                                            <div className="flex flex-wrap gap-2 justify-center">
                                                {prediction.supreme_court.top_scorelines.map((scoreObj, idx) => (
                                                    <div key={idx} className="flex flex-col items-center bg-black/40 border border-amber-500/20 rounded px-2 py-1">
                                                        {scoreObj.goal_range && (
                                                            <span className="text-[7px] text-slate-500 uppercase tracking-wide mb-0.5">{scoreObj.goal_range}</span>
                                                        )}
                                                        <span className="text-[10px] font-mono text-white font-bold">{scoreObj.score}</span>
                                                        <span className="text-[8px] text-amber-400 font-bold">{scoreObj.probability.toFixed(1)}%</span>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            )}

                            <div className="space-y-4">
                                <div className="bg-slate-800/40 p-3 rounded-lg border border-slate-700/50">
                                    <h5 className="text-xs font-bold text-slate-400 uppercase mb-1">Scenario A: The Expected Script</h5>
                                    <p className="text-sm text-slate-300">{prediction.scenario_analysis.scenario_a_expected_script}</p>
                                </div>
                                <div className="bg-slate-800/40 p-3 rounded-lg border border-slate-700/50">
                                    <h5 className="text-xs font-bold text-slate-400 uppercase mb-1">Scenario B: The Underdog Disruption</h5>
                                    <p className="text-sm text-slate-300">{prediction.scenario_analysis.scenario_b_underdog_disruption}</p>
                                </div>
                                {prediction.scenario_analysis.scenario_c_red_card_disruption && (
                                    <div className="bg-slate-800/40 p-3 rounded-lg border border-red-500/20">
                                        <h5 className="text-xs font-bold text-red-400 uppercase mb-1 flex items-center gap-1">
                                            <AlertTriangle className="w-3 h-3 text-red-400" /> Scenario C: The Red Card Disruption
                                        </h5>
                                        <p className="text-sm text-slate-300">{prediction.scenario_analysis.scenario_c_red_card_disruption}</p>
                                    </div>
                                )}
                            </div>
                        </div>
                    )
                }

                {/* AI Logic Dropdown (CoT) */}
                {
                    (prediction.supreme_court?.Internal_Logic_Override || prediction.step_by_step_reasoning) && (
                        <div className="mt-4 bg-slate-800/20 rounded-xl border border-slate-700/50 overflow-hidden transition-all duration-300">
                            <button
                                onClick={() => setShowLogic(!showLogic)}
                                className="w-full px-5 py-4 flex items-center justify-between hover:bg-slate-800/40 transition-colors"
                            >
                                <div className="flex items-center gap-2">
                                    <Bolt className="w-4 h-4 text-slate-400" />
                                    <span className="text-sm font-semibold text-slate-300">View AI Internal Logic</span>
                                    {prediction.supreme_court?.Internal_Logic_Override && (
                                        <span className="ml-2 px-2 py-0.5 bg-accent-purple/20 text-accent-purple text-[10px] uppercase font-bold rounded border border-accent-purple/30">
                                            SUPREME COURT OVERRIDE
                                        </span>
                                    )}
                                </div>
                                {showLogic ? (
                                    <ChevronUp className="w-4 h-4 text-slate-400" />
                                ) : (
                                    <ChevronDown className="w-4 h-4 text-slate-400" />
                                )}
                            </button>

                            {/* Expandable Content */}
                            <div className={`transition-all duration-300 ease-in-out ${showLogic ? 'max-h-[600px] overflow-y-auto opacity-100 p-5 pt-0' : 'max-h-0 opacity-0 overflow-hidden'}`}>
                                <div className="pt-4 border-t border-slate-700/50">
                                    <p className="text-sm text-slate-400 leading-relaxed whitespace-pre-wrap font-mono bg-black/20 p-4 rounded-lg">
                                        {prediction.supreme_court?.Internal_Logic_Override || prediction.step_by_step_reasoning}
                                    </p>
                                </div>
                            </div>
                        </div>
                    )
                }
                <div className="h-1.5 w-full bg-gradient-to-r from-primary via-accent-purple to-accent-green"></div>
            </div >

            {/* Modal for Expanded Insight */}
            {
                activeInsight && (
                    <InsightModal
                        market={activeInsight.market}
                        analysis={activeInsight.analysis}
                        onClose={() => setActiveInsight(null)}
                        getIcon={getMarketIcon}
                    />
                )
            }
        </>
    );
};

// Simplified Card Component (Triggers Modal)
const InsightCard = ({ market, analysis, index, isCorrection, getIcon, onClick }) => {
    // Basic Parsing for Preview - Handle both string and object formats
    let predictionText = 'N/A';
    if (typeof analysis === 'object' && analysis !== null) {
        predictionText = analysis.prediction || 'N/A';
    } else if (typeof analysis === 'string') {
        const parts = analysis.split('. ');
        predictionText = parts[0]?.replace('Prediction: ', '').replace('Prediction:', '') || 'N/A';
    }

    return (
        <div
            onClick={onClick}
            className={`group cursor-pointer bg-slate-800/30 border rounded-xl p-3 flex flex-col justify-between hover:bg-slate-800/80 transition-all duration-300 hover:scale-[1.02] hover:shadow-lg h-24 ${isCorrection
                ? 'border-indigo-500/50 shadow-indigo-500/10'
                : 'border-slate-700/50 hover:border-primary/50 hover:shadow-primary/10'
                }`}
        >
            <div className="flex justify-between items-start">
                <div className="flex flex-col">
                    <p className={`text-[10px] font-bold uppercase tracking-wide ${index % 2 === 0 ? 'text-accent-purple' : 'text-accent-green'}`}>
                        {market.replace(/_/g, " ")}
                    </p>
                    {isCorrection && (
                        <span className="text-[7px] font-black bg-indigo-500 text-white px-1 py-0.5 rounded uppercase mt-0.5 w-fit">Judicial Override</span>
                    )}
                </div>
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
    const isCorrection = analysis.isCorrection; // Check if passed via activeInsight object

    // Unified Parsing for both string and object (Agent 1 vs Risk Manager vs Supreme Court formats)
    let predictionText = 'N/A';
    let reasoningText = 'No detailed reasoning provided.';
    let oddsValue = null;

    if (typeof analysis === 'object' && analysis !== null && analysis.prediction) {
        // New Schema Format
        predictionText = analysis.prediction;
        reasoningText = analysis.reasoning || reasoningText;
        oddsValue = analysis.odds;
    } else {
        // Legacy String Format or Supreme Court Override string
        const finalAnalysis = typeof analysis === 'object' && analysis !== null ? (analysis.analysis || analysis.prediction) : analysis;
        if (typeof finalAnalysis === 'string') {
            const parts = finalAnalysis.split('. ');
            predictionText = parts[0]?.replace('Prediction: ', '').replace('Prediction:', '') || 'N/A';
            reasoningText = parts.slice(1).join('. ') || reasoningText;
        }
    }

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
                        <div className={`p-2 rounded-lg ${isCorrection ? 'bg-indigo-500/20 text-indigo-400' : 'bg-slate-700/50'}`}>
                            {getIcon(market)}
                        </div>
                        <div>
                            <div className="flex items-center gap-2">
                                <p className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                                    {market.replace(/_/g, " ")}
                                </p>
                                {isCorrection && (
                                    <span className="text-[8px] font-black bg-indigo-500 text-white px-2 py-0.5 rounded uppercase">Judicial Override</span>
                                )}
                            </div>
                            <h3 className="text-xl font-black text-white flex items-center gap-3">
                                {predictionText}
                                {oddsValue && (
                                    <span className="text-sm bg-primary/20 text-primary px-2 py-0.5 rounded border border-primary/30">
                                        @{oddsValue}
                                    </span>
                                )}
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
