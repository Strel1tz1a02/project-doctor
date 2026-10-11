package com.example.slowquery.dto;

import lombok.Data;

@Data
public class ArticleVO {
    private Long id;
    private String articleCode;
    private String title;
    private String authorName;
}
