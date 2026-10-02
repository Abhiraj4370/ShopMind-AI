import React from "react";
import {
    Check,
    Circle,
    LoaderCircle,
} from "lucide-react";

const steps = [
    "Understanding your request",
    "Discovering merchants",
    "Searching products",
    "Comparing prices",
    "Optimizing your order",
];

export default function LoadingSteps({
    activeStep = 0,
}) {
    return (
        <div className="loading-card">
            <div className="loading-header">
                <div className="ai-loader">
                    <LoaderCircle
                        size={25}
                        className="spin"
                    />
                </div>

                <div>
                    <h3>ShopMind AI is working</h3>

                    <p>
                        Finding the best option for you...
                    </p>
                </div>
            </div>

            <div className="loading-steps">
                {steps.map((step, index) => {
                    const completed =
                        index < activeStep;

                    const active =
                        index === activeStep;

                    return (
                        <div
                            className={`loading-step ${completed
                                    ? "completed"
                                    : ""
                                } ${active ? "active" : ""
                                }`}
                            key={step}
                        >
                            <div className="step-icon">
                                {completed ? (
                                    <Check size={15} />
                                ) : active ? (
                                    <LoaderCircle
                                        size={15}
                                        className="spin"
                                    />
                                ) : (
                                    <Circle size={12} />
                                )}
                            </div>

                            <span>{step}</span>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}