package com.example.slowquery.service;

import com.example.slowquery.dto.ArticleVO;
import com.example.slowquery.mapper.ArticleMapper;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class ArticleService {

    private final ArticleMapper articleMapper;

    public ArticleService(ArticleMapper articleMapper) {
        this.articleMapper = articleMapper;
    }

    public List<ArticleVO> findByAuthorCode(String authorCode) {
        return articleMapper.findByAuthorCode(authorCode);
    }
}
