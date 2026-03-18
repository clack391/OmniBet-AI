import React, { useState } from 'react';
import { Scale, Gavel, AlertTriangle, ChevronDown, ChevronUp, Plus, Check, ShieldAlert, Shield } from 'lucide-react';

const SupremeCourtCard = ({ supreme_court, handleAdd, isPickAdded }) => {
    const [isExpanded, setIsExpanded] = useState(false);

    if (!supreme_court) return null;

    const {
        verdict_status,
        Supreme_Court_Final_Ruling,
        supreme_court_reasoning,
        Arbiter_Safe_Pick,
        primary_safe_pick,
        Crucible_Simulation_Warning,
        variance_warning
    } = supreme_court;

    const final_ruling = Supreme_Court_Final_Ruling || supreme_court_reasoning;
    const safe_pick = Arbiter_Safe_Pick || primary_safe_pick;
    const variance = Crucible_Simulation_Warning || variance_warning;

    return (
        <div className="bg-gradient-to-br from-indigo-950 via-gray-900 to-slate-950 rounded-xl border-2 border-indigo-500/30 overflow-hidden shadow-2xl relative transition-all duration-500">
            {/* Background Decoration */}
            <div className="absolute top-0 right-0 p-3 opacity-10 pointer-events-none">
                <Gavel className="w-16 h-16 text-indigo-400 rotate-12" />
            </div>

            {/* Header */}
            <div className="p-3 bg-indigo-500/10 border-b border-indigo-500/20 flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <Scale className="w-4 h-4 text-indigo-400" />
                    <span className="text-[10px] font-black uppercase tracking-[0.2em] text-indigo-300">Supreme Court Final Ruling</span>
                </div>
                <div className={`text-[9px] font-black px-2 py-0.5 rounded border ${verdict_status === 'CONFIRMED' ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' :
                    verdict_status === 'OVERTURNED' ? 'bg-orange-500/20 text-orange-400 border-orange-500/30' :
                        verdict_status === 'NO_BET' ? 'bg-zinc-500/20 text-zinc-300 border-zinc-500/30' :
                            'bg-gray-500/20 text-gray-400 border-gray-500/30'
                    }`}>
                    {verdict_status === 'NO_BET' ? 'MATCH VETOED' : verdict_status}
                </div>
            </div>

            <div className="p-4 space-y-4">
                {/* Reasoning with Expand/Collapse */}
                <div className="relative">
                    <p className={`text-base text-indigo-50 leading-relaxed font-medium italic transition-all duration-300 ${isExpanded ? '' : 'line-clamp-3'}`}>
                        "{final_ruling}"
                    </p>
                    {final_ruling && final_ruling.length > 150 && (
                        <button
                            onClick={() => setIsExpanded(!isExpanded)}
                            className="mt-2 text-[10px] font-bold text-indigo-400 hover:text-indigo-300 uppercase tracking-widest flex items-center gap-1 transition-colors"
                        >
                            {isExpanded ? (
                                <><ChevronUp className="w-3 h-3" /> Show Less</>
                            ) : (
                                <><ChevronDown className="w-3 h-3" /> Show Full Judicial Opinion</>
                            )}
                        </button>
                    )}
                </div>

                {/* Picks Grid - Larger Text */}
                {verdict_status === 'NO_BET' ? (
                    <div className="bg-zinc-950/60 rounded-xl p-6 border-2 border-zinc-500/20 flex flex-col items-center justify-center text-center gap-4 relative overflow-hidden group">
                        <div className="absolute inset-0 bg-gradient-to-b from-zinc-500/5 to-transparent pointer-events-none" />
                        <div className="bg-zinc-500/10 p-4 rounded-full border border-zinc-500/20 group-hover:scale-110 transition-transform duration-500">
                            <ShieldAlert className="w-8 h-8 text-zinc-400" />
                        </div>
                        <div>
                            <div className="text-zinc-200 font-black text-lg uppercase tracking-wider mb-2">Capital Preservation Mode</div>
                            <div className="text-zinc-400 text-xs font-medium max-w-xs mx-auto leading-relaxed">
                                The Supreme Court has determined this fixture is too volatile for a safe mathematical edge. No bet is recommended.
                            </div>
                        </div>
                        <div className="flex items-center gap-2 px-3 py-1 bg-zinc-500/10 rounded-full border border-zinc-500/20">
                            <Shield className="w-3 h-3 text-zinc-500" />
                            <span className="text-[9px] font-bold text-zinc-500 uppercase tracking-tighter">Judicial Veto Active</span>
                        </div>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div className="bg-black/40 rounded-lg p-3 border border-indigo-500/15 group hover:border-indigo-500/30 transition-colors flex flex-col justify-between overflow-hidden">
                            <div className="mb-4">
                                <div className="text-[9px] text-indigo-400 font-bold uppercase mb-1 tracking-wider">Arbiter's Safe Pick</div>
                                <div className="flex items-center justify-between gap-2">
                                    <div className="text-base md:text-lg font-black text-white leading-tight break-words">{safe_pick?.tip || 'N/A'}</div>
                                    {safe_pick?.odds && (
                                        <div className="text-xs font-black text-indigo-400 bg-indigo-500/10 px-1.5 py-0.5 rounded shrink-0">
                                            @{parseFloat(safe_pick.odds).toFixed(2)}
                                        </div>
                                    )}
                                </div>
                                <div className="text-[10px] text-gray-500 uppercase tracking-tighter mt-0.5">{safe_pick?.market}</div>
                            </div>
                            {safe_pick?.tip && handleAdd && (
                                <button
                                    onClick={() => handleAdd(safe_pick, 'Primary')}
                                    disabled={isPickAdded(safe_pick.tip)}
                                    className={`w-full py-1.5 rounded text-[10px] font-black uppercase tracking-widest transition-all flex items-center justify-center gap-2 ${isPickAdded(safe_pick.tip)
                                        ? 'bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 cursor-default'
                                        : 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-900/40'
                                        }`}
                                >
                                    {isPickAdded(safe_pick.tip) ? <Check className="w-3 h-3" /> : <Plus className="w-3 h-3" />}
                                    {isPickAdded(safe_pick.tip) ? 'Added' : 'Add Arbiter'}
                                </button>
                            )}
                        </div>
                        <div className="bg-black/40 rounded-lg p-3 border border-purple-500/15 group hover:border-purple-500/30 transition-colors flex flex-col justify-between overflow-hidden">
                            <div className="mb-4">
                                <div className="text-[9px] text-purple-400 font-bold uppercase mb-1 tracking-wider">Expected Value (EV) Pick</div>
                                <div className="flex items-center justify-between gap-2">
                                    <div className="text-base md:text-lg font-black text-white leading-tight break-words">{alternative_value_pick?.tip || 'N/A'}</div>
                                    {alternative_value_pick?.odds && (
                                        <div className="text-xs font-black text-purple-400 bg-purple-500/10 px-1.5 py-0.5 rounded shrink-0">
                                            @{parseFloat(alternative_value_pick.odds).toFixed(2)}
                                        </div>
                                    )}
                                </div>
                                <div className="text-[10px] text-gray-500 uppercase tracking-tighter mt-0.5">{alternative_value_pick?.market}</div>
                            </div>
                            {alternative_value_pick?.tip && handleAdd && (
                                <button
                                    onClick={() => handleAdd(alternative_value_pick, 'Value')}
                                    disabled={isPickAdded(alternative_value_pick.tip)}
                                    className={`w-full py-1.5 rounded text-[10px] font-black uppercase tracking-widest transition-all flex items-center justify-center gap-2 ${isPickAdded(alternative_value_pick.tip)
                                        ? 'bg-purple-500/10 text-purple-400 border border-purple-500/20 cursor-default'
                                        : 'bg-purple-600 hover:bg-purple-500 text-white shadow-lg shadow-purple-900/40'
                                        }`}
                                >
                                    {isPickAdded(alternative_value_pick.tip) ? <Check className="w-3 h-3" /> : <Plus className="w-3 h-3" />}
                                    {isPickAdded(alternative_value_pick.tip) ? 'Added' : 'Add EV Pick'}
                                </button>
                            )}
                        </div>
                    </div>
                )}

                {/* Variance Warning - Larger Text */}
                {variance && (
                    <div className="bg-red-500/5 border border-red-500/20 rounded-lg p-3 flex gap-3 items-start">
                        <AlertTriangle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
                        <div className="text-sm text-red-200/90 italic">
                            <span className="font-black uppercase text-[10px] block mb-1 text-red-400 tracking-[0.1em]">Crucible Simulation Warning:</span>
                            {variance}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default SupremeCourtCard;
