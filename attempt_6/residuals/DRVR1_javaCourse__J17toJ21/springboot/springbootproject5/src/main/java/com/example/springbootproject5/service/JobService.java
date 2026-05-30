package com.example.springbootproject5.service;

import java.util.List;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import com.example.springbootproject5.model.Job;
import com.example.springbootproject5.repo.JobRepo;

@Service
public class JobService {
    @Autowired
    JobRepo jobRepo;

    public List<Job> getAllJobs() {
        return jobRepo.findAll();
    }

    public Job getJobById(long id) {
        Job ret = jobRepo.findById(id).get();
        return ret;
    }

    public Job createJob(Job job) {
        return jobRepo.save(job);
    }

    public Job updateJob(Job job) {
        Job oldJob = jobRepo.findById(job.getId()).get();
        oldJob.setName(job.getName());
        oldJob.setSalary(job.getSalary());
        return jobRepo.save(oldJob);
    }

    public boolean deleteJob(Job job) {
        jobRepo.deleteById(job.getId());
        return true;
    }
}
