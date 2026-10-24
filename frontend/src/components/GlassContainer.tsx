import React from 'react';

interface GlassContainerProps {
  children: React.ReactNode;
  className?: string;
  onClick?: () => void;
}

export const GlassContainer: React.FC<GlassContainerProps> = ({
  children,
  className = '',
  onClick,
}) => {
  return (
    <div
      onClick={onClick}
      className={`border border-neutral-700/60 bg-neutral-900/85 backdrop-blur-xl rounded-2xl shadow-2xl ${className}`}
    >
      {children}
    </div>
  );
};
