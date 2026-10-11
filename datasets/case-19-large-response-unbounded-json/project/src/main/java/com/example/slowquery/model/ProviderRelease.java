package com.example.slowquery.model;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class ProviderRelease {
    private Long id;
    private String provider;
    private String releaseTag;
    private String payload;
    private LocalDateTime createdAt;
}
