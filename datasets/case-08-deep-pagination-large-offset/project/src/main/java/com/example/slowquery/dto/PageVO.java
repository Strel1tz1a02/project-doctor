package com.example.slowquery.dto;

import lombok.Data;

import java.util.List;

@Data
public class PageVO {
    private int page;
    private int size;
    private long total;
    private List<OrderVO> items;
}
