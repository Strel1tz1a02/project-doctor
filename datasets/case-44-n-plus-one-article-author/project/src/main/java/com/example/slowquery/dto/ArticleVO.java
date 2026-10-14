package com.example.slowquery.dto;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class ArticleVO {
    private Long articleId;
    private String title;
    private String status;
    private LocalDateTime createdAt;
    private String authorName;
    private String authorEmail;
}
