package com.example.slowquery.service;

import com.example.slowquery.mapper.ArticleMapper;
import com.example.slowquery.model.Article;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class ArticleService {

    private final ArticleMapper articleMapper;

    public ArticleService(ArticleMapper articleMapper) {
        this.articleMapper = articleMapper;
    }

    public List<Article> search(String keyword, int limit) {
        return articleMapper.searchByTitle(keyword, limit);
    }
}
