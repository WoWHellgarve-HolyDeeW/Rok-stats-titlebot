"use client";
import { useState } from "react";

interface PlayerAvatarProps {
  name: string;
  avatarUrl?: string | null;
  size?: "sm" | "md" | "lg";
}

const sizes = {
  sm: "w-8 h-8 text-xs",
  md: "w-10 h-10 text-sm",
  lg: "w-14 h-14 text-base",
};

export default function PlayerAvatar({ name, avatarUrl, size = "md" }: PlayerAvatarProps) {
  const [failed, setFailed] = useState(false);
  const sizeClass = sizes[size];
  const initials = name ? name.substring(0, 2).toUpperCase() : "?";

  if (avatarUrl && !failed) {
    return (
      <img
        src={avatarUrl}
        alt={name}
        className={`${sizeClass} rounded-full object-cover`}
        onError={() => setFailed(true)}
        loading="lazy"
        referrerPolicy="no-referrer"
      />
    );
  }

  return (
    <div
      className={`${sizeClass} rounded-full bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center text-white font-bold`}
    >
      {initials}
    </div>
  );
}
