package com.example.slowquery.dto;

import lombok.Data;

@Data
public class SectionVO {
    private long sectionId;
    private String title;
    private String courseTitle;
    private long resourceCount;
}
