package com.example.slowquery.dto;

import lombok.Data;

import java.util.List;

@Data
public class PageVO {
    private int offset;
    private int limit;
    private long total;
    private List<ItemVO> items;
}
