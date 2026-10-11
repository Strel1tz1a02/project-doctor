package com.example.slowquery.dto;

import lombok.Data;

import java.util.List;

@Data
public class RunDetailVO {
    private List<RunJobVO> jobs;
    private List<JobLogVO> stepTimeline;
}
