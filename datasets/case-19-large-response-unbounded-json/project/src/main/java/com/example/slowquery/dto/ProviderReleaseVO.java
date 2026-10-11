package com.example.slowquery.dto;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class ProviderReleaseVO {
    private Long releaseId;
    private String provider;
    private String releaseTag;
    private LocalDateTime createdAt;
}
